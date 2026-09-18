// Copyright (C) 2026 Muhammad Saeed
//
// SPDX-License-Identifier: MIT

export interface ClassStatistics {
    label_id: number;
    name: string;
    color: string;
    type: string;
    image_count: number;
    annotation_count: number;
    shape_count: number;
    tag_count: number;
    track_count: number;
}

export interface ClassDistribution {
    task_id: number;
    task_name: string;
    job_id: number | null;
    total_frames: number;
    annotated_frames: number;
    total_annotations: number;
    classes: ClassStatistics[];
    generated_at: string;
}

export interface ServerFrame {
    type: 'snapshot' | 'heartbeat' | 'pong' | 'error';
    payload?: ClassDistribution;
    code?: string;
    detail?: string;
}

const API_PREFIX = '/api/test/class-distribution';

function buildQuery(jobID: number | null): string {
    return jobID === null ? '' : `?job_id=${jobID}`;
}

// The UI is served from the same origin as the API (nginx in production, the
// webpack dev-server proxy in development), so the session cookie is enough.
export async function fetchClassDistribution(
    taskID: number,
    jobID: number | null = null,
    signal?: AbortSignal,
): Promise<ClassDistribution> {
    const response = await fetch(`${API_PREFIX}/${taskID}${buildQuery(jobID)}`, {
        credentials: 'include',
        headers: { Accept: 'application/vnd.cvat+json; version=2.0' },
        signal,
    });

    if (!response.ok) {
        const detail = await response.text().catch(() => '');
        throw new Error(`Request failed with status ${response.status}. ${detail}`.trim());
    }

    return response.json();
}

export function classDistributionSocketURL(taskID: number, jobID: number | null = null): string {
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${scheme}://${window.location.host}/ws/test/class-distribution/${taskID}/${buildQuery(jobID)}`;
}
