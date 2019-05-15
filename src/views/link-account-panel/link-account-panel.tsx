// Copyright (C) The Arvados Authors. All rights reserved.
//
// SPDX-License-Identifier: AGPL-3.0

import { RootState } from '~/store/store';
import { Dispatch } from 'redux';
import { connect } from 'react-redux';
import { startLinking, cancelLinking, linkAccount, linkAccountPanelActions } from '~/store/link-account-panel/link-account-panel-actions';
import { LinkAccountType } from '~/models/link-account';
import {
    LinkAccountPanelRoot,
    LinkAccountPanelRootDataProps,
    LinkAccountPanelRootActionProps
} from '~/views/link-account-panel/link-account-panel-root';

const mapStateToProps = (state: RootState): LinkAccountPanelRootDataProps => {
    return {
        remoteHosts: state.auth.remoteHosts,
        hasRemoteHosts: Object.keys(state.auth.remoteHosts).length > 1,
        selectedCluster: state.linkAccountPanel.selectedCluster,
        targetUser: state.linkAccountPanel.targetUser,
        userToLink: state.linkAccountPanel.userToLink,
        status: state.linkAccountPanel.status,
        error: state.linkAccountPanel.error
    };
};

const mapDispatchToProps = (dispatch: Dispatch): LinkAccountPanelRootActionProps => ({
    startLinking: (type: LinkAccountType) => dispatch<any>(startLinking(type)),
    cancelLinking: () => dispatch<any>(cancelLinking()),
    linkAccount: () => dispatch<any>(linkAccount()),
    setSelectedCluster: (selectedCluster: string) => dispatch<any>(linkAccountPanelActions.SET_SELECTED_CLUSTER({selectedCluster}))
});

export const LinkAccountPanel = connect(mapStateToProps, mapDispatchToProps)(LinkAccountPanelRoot);
