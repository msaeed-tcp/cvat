// Copyright (C) 2026 Muhammad Saeed
//
// SPDX-License-Identifier: MIT

import { useCallback, useEffect, useRef, useState } from 'react';

import {
    ClassDistribution, ServerFrame, classDistributionSocketURL, fetchClassDistribution,
} from './api';

export enum ConnectionState {
    CONNECTING = 'connecting',
    LIVE = 'live',
    RECONNECTING = 'reconnecting',
    POLLING = 'polling',
    STOPPED = 'stopped',
}

export interface ClassDistributionStream {
    data: ClassDistribution | null;
    fetching: boolean;
    error: Error | null;
    connection: ConnectionState;
    refresh: () => void;
}

// Close codes the server uses for conditions that will not fix themselves.
// Retrying those would only produce a reconnect loop against a locked door.
const TERMINAL_CLOSE_CODES = new Set([4400, 4401, 4403, 4404]);

const BASE_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;
const ATTEMPTS_BEFORE_POLLING = 3;
const POLL_INTERVAL_MS = 15_000;
// The server sends a heartbeat every 25 s. Two missed heartbeats mean the
// connection is half-open - the socket looks alive but nothing arrives.
const SILENCE_TIMEOUT_MS = 60_000;

function backoffDelay(attempt: number): number {
    const exponential = Math.min(BASE_BACKOFF_MS * 2 ** attempt, MAX_BACKOFF_MS);
    // Jitter keeps many open tabs from reconnecting in lockstep after an outage.
    return exponential / 2 + Math.random() * (exponential / 2);
}

export default function useClassDistribution(
    taskID: number | null,
    jobID: number | null = null,
): ClassDistributionStream {
    const [data, setData] = useState<ClassDistribution | null>(null);
    const [fetching, setFetching] = useState<boolean>(true);
    const [error, setError] = useState<Error | null>(null);
    const [connection, setConnection] = useState<ConnectionState>(ConnectionState.CONNECTING);

    const socketRef = useRef<WebSocket | null>(null);
    const attemptRef = useRef<number>(0);
    const reconnectTimerRef = useRef<number | null>(null);
    const pollTimerRef = useRef<number | null>(null);
    const silenceTimerRef = useRef<number | null>(null);
    const disposedRef = useRef<boolean>(false);

    const clearTimer = (ref: { current: number | null }): void => {
        if (ref.current !== null) {
            window.clearTimeout(ref.current);
            ref.current = null;
        }
    };

    const loadOnce = useCallback(async (): Promise<void> => {
        if (taskID === null) return;

        try {
            const snapshot = await fetchClassDistribution(taskID, jobID);
            if (disposedRef.current) return;
            setData(snapshot);
            setError(null);
        } catch (caught: unknown) {
            if (disposedRef.current) return;
            setError(caught instanceof Error ? caught : new Error(String(caught)));
        } finally {
            if (!disposedRef.current) setFetching(false);
        }
    }, [taskID, jobID]);

    const stopPolling = useCallback((): void => {
        if (pollTimerRef.current !== null) {
            window.clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
        }
    }, []);

    const startPolling = useCallback((): void => {
        if (pollTimerRef.current !== null) return;
        setConnection(ConnectionState.POLLING);
        pollTimerRef.current = window.setInterval(() => { loadOnce(); }, POLL_INTERVAL_MS);
    }, [loadOnce]);

    const connect = useCallback((): void => {
        if (taskID === null || disposedRef.current) return;
        if (socketRef.current && socketRef.current.readyState <= WebSocket.OPEN) return;

        let socket: WebSocket;
        try {
            socket = new WebSocket(classDistributionSocketURL(taskID, jobID));
        } catch {
            startPolling();
            return;
        }

        socketRef.current = socket;

        const armSilenceWatchdog = (): void => {
            clearTimer(silenceTimerRef);
            silenceTimerRef.current = window.setTimeout(() => {
                // Nothing arrived for a full silence window. Drop the socket and
                // let onclose run the normal reconnect path.
                socket.close();
            }, SILENCE_TIMEOUT_MS);
        };

        socket.onopen = (): void => {
            attemptRef.current = 0;
            setConnection(ConnectionState.LIVE);
            stopPolling();
            armSilenceWatchdog();
        };

        socket.onmessage = (event: MessageEvent): void => {
            armSilenceWatchdog();

            let frame: ServerFrame;
            try {
                frame = JSON.parse(event.data);
            } catch {
                return;
            }

            if (frame.type === 'snapshot' && frame.payload) {
                setData(frame.payload);
                setError(null);
                setFetching(false);
                setConnection(ConnectionState.LIVE);
            } else if (frame.type === 'error') {
                setError(new Error(frame.detail ?? 'The analytics stream reported an error'));
            }
        };

        socket.onclose = (event: CloseEvent): void => {
            clearTimer(silenceTimerRef);
            socketRef.current = null;
            if (disposedRef.current) return;

            if (TERMINAL_CLOSE_CODES.has(event.code)) {
                setConnection(ConnectionState.STOPPED);
                return;
            }

            const attempt = attemptRef.current;
            attemptRef.current = attempt + 1;

            if (attempt >= ATTEMPTS_BEFORE_POLLING) {
                // The socket is not coming back soon. Keep the page useful with
                // periodic REST reads while retries continue in the background.
                startPolling();
            } else {
                setConnection(ConnectionState.RECONNECTING);
            }

            reconnectTimerRef.current = window.setTimeout(connect, backoffDelay(attempt));
        };

        socket.onerror = (): void => {
            // onerror is always followed by onclose, which owns the retry logic.
        };
    }, [taskID, jobID, startPolling, stopPolling]);

    const refresh = useCallback((): void => {
        const socket = socketRef.current;
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'refresh' }));
        } else {
            loadOnce();
        }
    }, [loadOnce]);

    useEffect(() => {
        disposedRef.current = false;
        attemptRef.current = 0;
        setFetching(true);
        setConnection(ConnectionState.CONNECTING);

        // Paint from REST immediately; the socket then takes over for updates.
        loadOnce();
        connect();

        const onVisibilityChange = (): void => {
            if (document.visibilityState === 'visible') {
                attemptRef.current = 0;
                loadOnce();
                connect();
            }
        };

        document.addEventListener('visibilitychange', onVisibilityChange);

        return () => {
            disposedRef.current = true;
            document.removeEventListener('visibilitychange', onVisibilityChange);
            clearTimer(reconnectTimerRef);
            clearTimer(silenceTimerRef);
            stopPolling();
            if (socketRef.current) {
                socketRef.current.onclose = null;
                socketRef.current.close(1000, 'Page closed');
                socketRef.current = null;
            }
        };
    }, [connect, loadOnce, stopPolling]);

    return {
        data, fetching, error, connection, refresh,
    };
}
