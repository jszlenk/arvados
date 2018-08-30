// Copyright (C) The Arvados Authors. All rights reserved.
//
// SPDX-License-Identifier: AGPL-3.0

import * as React from 'react';
import { StyleRulesCallback, WithStyles, withStyles } from '@material-ui/core/styles';
import { connect, DispatchProp } from "react-redux";
import { Route, Switch } from "react-router";
import { login, logout } from "~/store/auth/auth-action";
import { User } from "~/models/user";
import { RootState } from "~/store/store";
import { MainAppBar, MainAppBarActionProps, MainAppBarMenuItem } from '~/views-components/main-app-bar/main-app-bar';
import { push } from 'react-router-redux';
import { ProjectPanel } from "~/views/project-panel/project-panel";
import { DetailsPanel } from '~/views-components/details-panel/details-panel';
import { ArvadosTheme } from '~/common/custom-theme';
import { detailsPanelActions } from "~/store/details-panel/details-panel-action";
import { ContextMenu } from "~/views-components/context-menu/context-menu";
import { FavoritePanel } from "../favorite-panel/favorite-panel";
import { CurrentTokenDialog } from '~/views-components/current-token-dialog/current-token-dialog';
import { Snackbar } from '~/views-components/snackbar/snackbar';
import { CollectionPanel } from '../collection-panel/collection-panel';
import { AuthService } from "~/services/auth-service/auth-service";
import { RenameFileDialog } from '~/views-components/rename-file-dialog/rename-file-dialog';
import { FileRemoveDialog } from '~/views-components/file-remove-dialog/file-remove-dialog';
import { MultipleFilesRemoveDialog } from '~/views-components/file-remove-dialog/multiple-files-remove-dialog';
import { Routes } from '~/routes/routes';
import { SidePanel } from '~/views-components/side-panel/side-panel';
import { ProcessPanel } from '~/views/process-panel/process-panel';
import { Breadcrumbs } from '~/views-components/breadcrumbs/breadcrumbs';
import { CreateProjectDialog } from '~/views-components/dialog-forms/create-project-dialog';
import { CreateCollectionDialog } from '~/views-components/dialog-forms/create-collection-dialog';
import { CopyCollectionDialog } from '~/views-components/dialog-forms/copy-collection-dialog';
import { UpdateCollectionDialog } from '~/views-components/dialog-forms/update-collection-dialog';
import { UpdateProjectDialog } from '~/views-components/dialog-forms/update-project-dialog';
import { MoveProjectDialog } from '~/views-components/dialog-forms/move-project-dialog';
import { MoveCollectionDialog } from '~/views-components/dialog-forms/move-collection-dialog';

import { FilesUploadCollectionDialog } from '~/views-components/dialog-forms/files-upload-collection-dialog';
import { PartialCopyCollectionDialog } from '~/views-components/dialog-forms/partial-copy-collection-dialog';

import { TrashPanel } from "~/views/trash-panel/trash-panel";
import { trashPanelActions } from "~/store/trash-panel/trash-panel-action";

const APP_BAR_HEIGHT = 100;

type CssRules = 'root' | 'appBar' | 'content' | 'contentWrapper';

const styles: StyleRulesCallback<CssRules> = (theme: ArvadosTheme) => ({
    root: {
        flexGrow: 1,
        zIndex: 1,
        overflow: 'hidden',
        position: 'relative',
        display: 'flex',
        width: '100vw',
        height: '100vh'
    },
    appBar: {
        zIndex: theme.zIndex.drawer + 1,
        position: "absolute",
        width: "100%"
    },
    contentWrapper: {
        backgroundColor: theme.palette.background.default,
        display: "flex",
        flexGrow: 1,
        minWidth: 0,
        paddingTop: APP_BAR_HEIGHT
    },
    content: {
        padding: `${theme.spacing.unit}px ${theme.spacing.unit * 3}px`,
        overflowY: "auto",
        flexGrow: 1,
        position: 'relative'
    },
});

interface WorkbenchDataProps {
    user?: User;
    currentToken?: string;
}

interface WorkbenchGeneralProps {
    authService: AuthService;
    buildInfo: string;
}

interface WorkbenchActionProps {
}

type WorkbenchProps = WorkbenchDataProps & WorkbenchGeneralProps & WorkbenchActionProps & DispatchProp<any> & WithStyles<CssRules>;

interface NavMenuItem extends MainAppBarMenuItem {
    action: () => void;
}

interface WorkbenchState {
    isCurrentTokenDialogOpen: boolean;
    anchorEl: any;
    searchText: string;
    menuItems: {
        accountMenu: NavMenuItem[],
        helpMenu: NavMenuItem[],
        anonymousMenu: NavMenuItem[]
    };
}

export const Workbench = withStyles(styles)(
    connect<WorkbenchDataProps>(
        (state: RootState) => ({
            user: state.auth.user,
            currentToken: state.auth.apiToken,
        })
    )(
        class extends React.Component<WorkbenchProps, WorkbenchState> {
            state = {
                isCurrentTokenDialogOpen: false,
                anchorEl: null,
                searchText: "",
                breadcrumbs: [],
                menuItems: {
                    accountMenu: [
                        {
                            label: 'Current token',
                            action: () => this.toggleCurrentTokenModal()
                        },
                        {
                            label: "Logout",
                            action: () => this.props.dispatch(logout())
                        },
                        {
                            label: "My account",
                            action: () => this.props.dispatch(push("/my-account"))
                        }
                    ],
                    helpMenu: [
                        {
                            label: "Help",
                            action: () => this.props.dispatch(push("/help"))
                        }
                    ],
                    anonymousMenu: [
                        {
                            label: "Sign in",
                            action: () => this.props.dispatch(login())
                        }
                    ]
                }
            };

            render() {
                const { classes, user } = this.props;
                return (
                    <div className={classes.root}>
                        <div className={classes.appBar}>
                            <MainAppBar
                                breadcrumbs={Breadcrumbs}
                                searchText={this.state.searchText}
                                user={this.props.user}
                                menuItems={this.state.menuItems}
                                buildInfo={this.props.buildInfo}
                                {...this.mainAppBarActions} />
                        </div>
                        {user && <SidePanel />}
                        <main className={classes.contentWrapper}>
                            <div className={classes.content}>
                                <Switch>
                                    <Route path={Routes.PROJECTS} component={ProjectPanel} />
                                    <Route path={Routes.COLLECTIONS} component={CollectionPanel} />
                                    <Route path={Routes.FAVORITES} component={FavoritePanel} />
                                    <Route path={Routes.PROCESSES} component={ProcessPanel} />
                                    <Route path="/trash" render={this.renderTrashPanel} />
                                </Switch>
                            </div>
                            {user && <DetailsPanel />}
                        </main>
                        <ContextMenu />
                        <Snackbar />
                        <CreateProjectDialog />
                        <CreateCollectionDialog />
                        <RenameFileDialog />
                        <PartialCopyCollectionDialog />
                        <FileRemoveDialog />
                        <CopyCollectionDialog />
                        <FileRemoveDialog />
                        <MultipleFilesRemoveDialog />
                        <UpdateCollectionDialog />
                        <FilesUploadCollectionDialog />
                        <UpdateProjectDialog />
                        <MoveCollectionDialog />
                        <MoveProjectDialog />
                        <CurrentTokenDialog
                            currentToken={this.props.currentToken}
                            open={this.state.isCurrentTokenDialogOpen}
                            handleClose={this.toggleCurrentTokenModal} />
                    </div>
                );
            }

            mainAppBarActions: MainAppBarActionProps = {
                onSearch: searchText => {
                    this.setState({ searchText });
                    this.props.dispatch(push(`/search?q=${searchText}`));
                },
                onMenuItemClick: (menuItem: NavMenuItem) => menuItem.action(),
                onDetailsPanelToggle: () => {
                    this.props.dispatch(detailsPanelActions.TOGGLE_DETAILS_PANEL());
                },
            };

            toggleCurrentTokenModal = () => {
                this.setState({ isCurrentTokenDialogOpen: !this.state.isCurrentTokenDialogOpen });
            }
        }
    )
);
