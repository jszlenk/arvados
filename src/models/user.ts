// Copyright (C) The Arvados Authors. All rights reserved.
//
// SPDX-License-Identifier: AGPL-3.0

import { Resource, ResourceKind } from '~/models/resource';

export interface User {
    email: string;
    firstName: string;
    lastName: string;
    uuid: string;
    ownerUuid: string;
    isAdmin: boolean;
}

export const getUserFullname = (user?: User) => {
    return user ? `${user.firstName} ${user.lastName}` : "";
};

export interface UserResource extends Resource {
    kind: ResourceKind.USER;
    email: string;
    username: string;
    firstName: string;
    lastName: string;
    identityUrl: string;
    isAdmin: boolean;
    prefs: UserPrefs;
    defaultOwnerUuid: string;
    isActive: boolean;
    writableBy: string[];
}

export interface UserPrefs {
    profile: {
        lab: string;
        organization: string;
        organizationEmail: string;
        role: string;
        websiteUrl: string;
    };
}