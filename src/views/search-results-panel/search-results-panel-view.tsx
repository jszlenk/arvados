// Copyright (C) The Arvados Authors. All rights reserved.
//
// SPDX-License-Identifier: AGPL-3.0

import * as React from 'react';
import { SortDirection } from '~/components/data-table/data-column';
import { DataColumns } from '~/components/data-table/data-table';
import { DataTableFilterItem } from '~/components/data-table-filters/data-table-filters';
import { ResourceKind } from '~/models/resource';
import { ContainerRequestState } from '~/models/container-request';
import { SearchBarAdvanceFormData } from '~/models/search-bar';
import { SEARCH_RESULTS_PANEL_ID } from '~/store/search-results-panel/search-results-panel-actions';
import { DataExplorer } from '~/views-components/data-explorer/data-explorer';
import {
    ProcessStatus, ResourceCluster,
    ResourceFileSize,
    ResourceLastModifiedDate,
    ResourceName,
    ResourceOwner,
    ResourceType
} from '~/views-components/data-explorer/renderers';
import { createTree } from '~/models/tree';
import { getInitialResourceTypeFilters } from '~/store/resource-type-filters/resource-type-filters';
import { User } from "~/models/user";
import { Config } from '~/common/config';
import { Session } from "~/models/session";

export enum SearchResultsPanelColumnNames {
    CLUSTER = "Cluster",
    NAME = "Name",
    PROJECT = "Project",
    STATUS = "Status",
    TYPE = 'Type',
    OWNER = "Owner",
    FILE_SIZE = "File size",
    LAST_MODIFIED = "Last modified"
}

export interface SearchResultsPanelDataProps {
    data: SearchBarAdvanceFormData;
    user: User;
    sessions: Session[];
    remoteHostsConfig: { [key: string]: Config };
    localCluster: string;
}

export interface SearchResultsPanelActionProps {
    onItemClick: (item: string) => void;
    onContextMenu: (event: React.MouseEvent<HTMLElement>, item: string) => void;
    onDialogOpen: (ownerUuid: string) => void;
    onItemDoubleClick: (item: string) => void;
}

export type SearchResultsPanelProps = SearchResultsPanelDataProps & SearchResultsPanelActionProps;

export interface WorkflowPanelFilter extends DataTableFilterItem {
    type: ResourceKind | ContainerRequestState;
}

export const searchResultsPanelColumns: DataColumns<string> = [
    {
        name: SearchResultsPanelColumnNames.CLUSTER,
        selected: true,
        configurable: true,
        filters: createTree(),
        render: (uuid: string) => <ResourceCluster uuid={uuid} />
    },
    {
        name: SearchResultsPanelColumnNames.NAME,
        selected: true,
        configurable: true,
        sortDirection: SortDirection.NONE,
        filters: createTree(),
        render: (uuid: string) => <ResourceName uuid={uuid} />
    },
    {
        name: SearchResultsPanelColumnNames.PROJECT,
        selected: true,
        configurable: true,
        filters: createTree(),
        render: uuid => <ResourceFileSize uuid={uuid} />
    },
    {
        name: SearchResultsPanelColumnNames.STATUS,
        selected: true,
        configurable: true,
        filters: createTree(),
        render: uuid => <ProcessStatus uuid={uuid} />
    },
    {
        name: SearchResultsPanelColumnNames.TYPE,
        selected: true,
        configurable: true,
        filters: getInitialResourceTypeFilters(),
        render: (uuid: string) => <ResourceType uuid={uuid} />,
    },
    {
        name: SearchResultsPanelColumnNames.OWNER,
        selected: true,
        configurable: true,
        filters: createTree(),
        render: uuid => <ResourceOwner uuid={uuid} />
    },
    {
        name: SearchResultsPanelColumnNames.FILE_SIZE,
        selected: true,
        configurable: true,
        filters: createTree(),
        render: uuid => <ResourceFileSize uuid={uuid} />
    },
    {
        name: SearchResultsPanelColumnNames.LAST_MODIFIED,
        selected: true,
        configurable: true,
        sortDirection: SortDirection.DESC,
        filters: createTree(),
        render: uuid => <ResourceLastModifiedDate uuid={uuid} />
    }
];

export const SearchResultsPanelView = (props: SearchResultsPanelProps) => {
    const homeCluster = props.user.uuid.substr(0, 5);
    return <DataExplorer
        id={SEARCH_RESULTS_PANEL_ID}
        onRowClick={props.onItemClick}
        onRowDoubleClick={props.onItemDoubleClick}
        onContextMenu={props.onContextMenu}
        contextMenuColumn={true}
        hideSearchInput
        header={
            props.localCluster === homeCluster ?
                <p>Searching clusters: {props.sessions.filter((ss) => ss.loggedIn).map((ss) => <span key={ss.clusterId}> {ss.clusterId}</span>)}</p> :
                <p>Searching local cluster {props.localCluster} only.  To search multiple clusters, <a href={props.remoteHostsConfig[homeCluster] && props.remoteHostsConfig[homeCluster].workbench2Url}> start from your home Workbench.</a></p>
        }
    />;
};
