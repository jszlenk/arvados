// Copyright (C) The Arvados Authors. All rights reserved.
//
// SPDX-License-Identifier: AGPL-3.0

import * as _ from "lodash";
import { CommonResourceService, ListResults } from "~/common/api/common-resource-service";
import { AxiosInstance } from "axios";
import { GroupResource } from "~/models/group";
import { CollectionResource } from "~/models/collection";
import { ProjectResource } from "~/models/project";
import { ProcessResource } from "~/models/process";

export interface ContentsArguments {
    limit?: number;
    offset?: number;
    order?: string;
    filters?: string;
    recursive?: boolean;
}

export type GroupContentsResource =
    CollectionResource |
    ProjectResource |
    ProcessResource;

export class GroupsService<T extends GroupResource = GroupResource> extends CommonResourceService<T> {

    constructor(serverApi: AxiosInstance) {
        super(serverApi, "groups");
    }

    contents(uuid: string, args: ContentsArguments = {}): Promise<ListResults<GroupContentsResource>> {
        const { filters, order, ...other } = args;
        const params = {
            ...other,
            filters: filters ? `[${filters}]` : undefined,
            order: order ? order : undefined
        };
        return this.serverApi
            .get(this.resourceType + `${uuid}/contents/`, {
                params: CommonResourceService.mapKeys(_.snakeCase)(params)
            })
            .then(CommonResourceService.mapResponseKeys);
    }
}

export enum GroupContentsResourcePrefix {
    COLLECTION = "collections",
    PROJECT = "groups",
    PROCESS = "container_requests"
}
