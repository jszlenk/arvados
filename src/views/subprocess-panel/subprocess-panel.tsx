// Copyright (C) The Arvados Authors. All rights reserved.
//
// SPDX-License-Identifier: AGPL-3.0

import { Dispatch } from "redux";
import { connect } from "react-redux";
import { openContextMenu, resourceKindToContextMenuKind } from '~/store/context-menu/context-menu-actions';
import { SubprocessPanelRoot, SubprocessPanelActionProps, SubprocessPanelDataProps } from '~/views/subprocess-panel/subprocess-panel-root';
import { ResourceKind } from '~/models/resource';
import { RootState } from "~/store/store";
import { navigateTo } from "~/store/navigation/navigation-action";
import { loadDetailsPanel } from "~/store/details-panel/details-panel-action";

const mapDispatchToProps = (dispatch: Dispatch): SubprocessPanelActionProps => ({
    onContextMenu: (event, resourceUuid, isAdmin) => {
        const kind = resourceKindToContextMenuKind(resourceUuid);
        if (kind) {
            dispatch<any>(openContextMenu(event, {
                name: '',
                uuid: resourceUuid,
                ownerUuid: '',
                kind: ResourceKind.PROCESS,
                menuKind: kind
            }));
        }
    },
    onItemClick: (uuid: string) => {
        dispatch<any>(loadDetailsPanel(uuid));
    },
    onItemDoubleClick: uuid => {
        dispatch<any>(navigateTo(uuid));
    }
});

const mapStateToProps = (state: RootState): SubprocessPanelDataProps => ({
    isAdmin: state.auth.user ? state.auth.user.isAdmin : false
});

export const SubprocessPanel = connect(mapStateToProps, mapDispatchToProps)(SubprocessPanelRoot);