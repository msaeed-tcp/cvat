// Copyright (C) 2026 Muhammad Saeed
//
// SPDX-License-Identifier: MIT

import React from 'react';
import Table from 'antd/lib/table';

import { ClassStatistics } from './api';

interface Props {
    classes: ClassStatistics[];
    totalFrames: number;
}

// The table is the non-visual equivalent of the chart: same numbers, readable
// by a screen reader, and copyable. Every chart in this page has one.
function ClassDistributionTable(props: Readonly<Props>): JSX.Element {
    const { classes, totalFrames } = props;

    const columns = [
        {
            title: 'Class',
            dataIndex: 'name',
            key: 'name',
            render: (name: string, record: ClassStatistics): JSX.Element => (
                <span className='cvat-class-distribution-swatch-cell'>
                    <i
                        className='cvat-class-distribution-swatch'
                        style={{ background: record.color || '#1890ff' }}
                    />
                    {name}
                </span>
            ),
        },
        {
            title: 'Images',
            dataIndex: 'image_count',
            key: 'image_count',
            sorter: (a: ClassStatistics, b: ClassStatistics): number => a.image_count - b.image_count,
        },
        {
            title: 'Share of frames',
            key: 'share',
            render: (_: unknown, record: ClassStatistics): string => (
                totalFrames > 0 ? `${((record.image_count / totalFrames) * 100).toFixed(1)}%` : 'n/a'
            ),
        },
        {
            title: 'Annotations',
            dataIndex: 'annotation_count',
            key: 'annotation_count',
            sorter: (a: ClassStatistics, b: ClassStatistics): number => (
                a.annotation_count - b.annotation_count
            ),
        },
        { title: 'Shapes', dataIndex: 'shape_count', key: 'shape_count' },
        { title: 'Tags', dataIndex: 'tag_count', key: 'tag_count' },
        { title: 'Tracks', dataIndex: 'track_count', key: 'track_count' },
    ];

    return (
        <Table
            className='cvat-class-distribution-table'
            rowKey={(record: ClassStatistics): number => record.label_id}
            columns={columns}
            dataSource={classes}
            size='small'
            pagination={false}
        />
    );
}

export default React.memo(ClassDistributionTable);
