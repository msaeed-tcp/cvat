// Copyright (C) 2026 Muhammad Saeed
//
// SPDX-License-Identifier: MIT

import React, { useMemo } from 'react';
import {
    BarElement,
    CategoryScale,
    Chart as ChartJS,
    ChartOptions,
    LinearScale,
    Tooltip,
    TooltipItem,
} from 'chart.js';
import ChartDataLabels from 'chartjs-plugin-datalabels';
import { Bar } from 'react-chartjs-2';

import { ClassStatistics } from './api';

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip);

// Labels created without an explicit color fall back to CVAT's accent blue.
// Identity is carried by the category axis, so a shared fallback is safe.
const FALLBACK_COLOR = '#1890ff';
const GRID_COLOR = 'rgba(0, 0, 0, 0.08)';
const INK_SECONDARY = 'rgba(0, 0, 0, 0.65)';
const DIRECT_LABEL_LIMIT = 12;
const ROW_HEIGHT = 34;
const MIN_HEIGHT = 220;

interface Props {
    classes: ClassStatistics[];
    totalFrames: number;
}

function ClassDistributionChart(props: Readonly<Props>): JSX.Element {
    const { classes, totalFrames } = props;

    const chartData = useMemo(() => ({
        labels: classes.map((item) => item.name),
        datasets: [{
            label: 'Images',
            data: classes.map((item) => item.image_count),
            backgroundColor: classes.map((item) => item.color || FALLBACK_COLOR),
            borderRadius: 4,
            borderSkipped: 'start' as const,
            categoryPercentage: 0.8,
            barPercentage: 0.9,
        }],
    }), [classes]);

    const options = useMemo<ChartOptions<'bar'>>(() => ({
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 250 },
        layout: { padding: { right: 48 } },
        scales: {
            x: {
                beginAtZero: true,
                grid: { color: GRID_COLOR, drawTicks: false },
                border: { display: false },
                ticks: { color: INK_SECONDARY, precision: 0 },
                title: { display: true, text: 'Images', color: INK_SECONDARY },
            },
            y: {
                grid: { display: false },
                border: { display: false },
                ticks: { color: INK_SECONDARY, autoSkip: false },
            },
        },
        plugins: {
            // One measure, one series: the title names it, so a legend box
            // would only repeat itself.
            legend: { display: false },
            tooltip: {
                callbacks: {
                    label: (context: TooltipItem<'bar'>): string[] => {
                        const item = classes[context.dataIndex];
                        const share = totalFrames > 0 ?
                            ` (${((item.image_count / totalFrames) * 100).toFixed(1)}% of frames)` : '';
                        return [
                            `Images: ${item.image_count}${share}`,
                            `Annotations: ${item.annotation_count}`,
                            `Shapes ${item.shape_count} | tags ${item.tag_count} | tracks ${item.track_count}`,
                        ];
                    },
                },
            },
            datalabels: {
                // Direct labels only while they stay readable; past that the
                // tooltip and the table view carry the exact numbers.
                display: classes.length <= DIRECT_LABEL_LIMIT,
                anchor: 'end',
                align: 'right',
                offset: 6,
                color: INK_SECONDARY,
                formatter: (value: number): string => `${value}`,
            },
        },
    }), [classes, totalFrames]);

    const height = Math.max(MIN_HEIGHT, classes.length * ROW_HEIGHT);

    return (
        <div className='cvat-class-distribution-chart' style={{ height }}>
            <Bar data={chartData} options={options} plugins={[ChartDataLabels]} />
        </div>
    );
}

export default React.memo(ClassDistributionChart);
