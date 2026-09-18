// Copyright (C) 2026 Muhammad Saeed
//
// SPDX-License-Identifier: MIT

import './styles.scss';

import React, { useState } from 'react';
import { useParams } from 'react-router';
import { Col, Row } from 'antd/lib/grid';
import Alert from 'antd/lib/alert';
import Badge from 'antd/lib/badge';
import Button from 'antd/lib/button';
import Empty from 'antd/lib/empty';
import Segmented from 'antd/lib/segmented';
import Statistic from 'antd/lib/statistic';
import Title from 'antd/lib/typography/Title';
import Text from 'antd/lib/typography/Text';
import Tooltip from 'antd/lib/tooltip';
import { ReloadOutlined } from '@ant-design/icons';

import CVATLoadingSpinner from 'components/common/loading-spinner';
import GoBackButton from 'components/common/go-back-button';

import ClassDistributionChart from './class-distribution-chart';
import ClassDistributionTable from './class-distribution-table';
import useClassDistribution, { ConnectionState } from './use-class-distribution';

type View = 'Chart' | 'Table';

const CONNECTION_LABELS: Record<ConnectionState, { status: 'success' | 'processing' | 'warning' | 'default'; text: string }> = {
    [ConnectionState.CONNECTING]: { status: 'processing', text: 'Connecting' },
    [ConnectionState.LIVE]: { status: 'success', text: 'Live' },
    [ConnectionState.RECONNECTING]: { status: 'warning', text: 'Reconnecting' },
    [ConnectionState.POLLING]: { status: 'warning', text: 'Refreshing every 15s' },
    [ConnectionState.STOPPED]: { status: 'default', text: 'Updates stopped' },
};

function ClassDistributionPage(): JSX.Element {
    const { tid } = useParams<{ tid: string }>();
    const taskID = Number.parseInt(tid, 10);
    const [view, setView] = useState<View>('Chart');

    const {
        data, fetching, error, connection, refresh,
    } = useClassDistribution(Number.isNaN(taskID) ? null : taskID);

    const connectionLabel = CONNECTION_LABELS[connection];
    const hasAnnotations = !!data && data.classes.some((item) => item.image_count > 0);

    return (
        <div className='cvat-class-distribution-page'>
            <Row>
                <Col span={24}>
                    <GoBackButton />
                </Col>
            </Row>

            <Row className='cvat-class-distribution-header'>
                <Col>
                    <Title level={4}>
                        {data ? `Class distribution: ${data.task_name}` : 'Class distribution'}
                    </Title>
                    <Text type='secondary'>
                        How many images contain at least one annotation of each class
                    </Text>
                </Col>
                <Col>
                    <span className='cvat-class-distribution-status'>
                        <Badge status={connectionLabel.status} text={connectionLabel.text} />
                        <Segmented
                            value={view}
                            options={['Chart', 'Table']}
                            onChange={(value) => setView(value as View)}
                        />
                        <Tooltip title='Recompute now'>
                            <Button icon={<ReloadOutlined />} onClick={refresh} />
                        </Tooltip>
                    </span>
                </Col>
            </Row>

            {error && (
                <Alert
                    className='cvat-class-distribution-alert'
                    type='error'
                    showIcon
                    message='Could not load class statistics'
                    description={error.message}
                />
            )}

            {data && (
                <Row gutter={16} className='cvat-class-distribution-summary'>
                    <Col span={6}><Statistic title='Classes' value={data.classes.length} /></Col>
                    <Col span={6}><Statistic title='Frames in task' value={data.total_frames} /></Col>
                    <Col span={6}><Statistic title='Annotated frames' value={data.annotated_frames} /></Col>
                    <Col span={6}><Statistic title='Annotations' value={data.total_annotations} /></Col>
                </Row>
            )}

            <div className='cvat-class-distribution-body'>
                {fetching && !data && <CVATLoadingSpinner />}

                {data && !hasAnnotations && (
                    <Empty description='No annotations yet. Draw a shape and this page updates by itself.' />
                )}

                {data && hasAnnotations && view === 'Chart' && (
                    <ClassDistributionChart classes={data.classes} totalFrames={data.total_frames} />
                )}

                {data && hasAnnotations && view === 'Table' && (
                    <ClassDistributionTable classes={data.classes} totalFrames={data.total_frames} />
                )}
            </div>

            {data && (
                <Text type='secondary'>
                    {`Last updated ${new Date(data.generated_at).toLocaleTimeString()}`}
                </Text>
            )}
        </div>
    );
}

export default React.memo(ClassDistributionPage);
