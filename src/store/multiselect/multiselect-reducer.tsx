// Copyright (C) The Arvados Authors. All rights reserved.
//
// SPDX-License-Identifier: AGPL-3.0

import { multiselectActionContants } from "./multiselect-actions";
import { TCheckedList } from "components/data-table/data-table";

type MultiselectToolbarState = {
    isVisible: boolean;
    checkedList: TCheckedList;
    selectedUuid: string;
};

const multiselectToolbarInitialState = {
    isVisible: false,
    checkedList: {},
    selectedUuid: '',
};

const { TOGGLE_VISIBLITY, SET_CHECKEDLIST, SELECT_ONE, DESELECT_ONE, TOGGLE_ONE, SET_SELECTED_UUID } = multiselectActionContants;

export const multiselectReducer = (state: MultiselectToolbarState = multiselectToolbarInitialState, action) => {
    switch (action.type) {
        case TOGGLE_VISIBLITY:
            return { ...state, isVisible: action.payload };
        case SET_CHECKEDLIST:
            return { ...state, checkedList: action.payload };
        case SELECT_ONE:
            return { ...state, checkedList: { ...state.checkedList, [action.payload]: true } };
        case DESELECT_ONE:
            return { ...state, checkedList: { ...state.checkedList, [action.payload]: false } };
        case TOGGLE_ONE:
            return { ...state, checkedList: { ...state.checkedList, [action.payload]: !state.checkedList[action.payload] } };
        case SET_SELECTED_UUID:
            return {...state, selectedUuid: action.payload || ''}
        default:
            return state;
    }
};
