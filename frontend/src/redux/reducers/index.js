import { combineReducers } from 'redux';
import { routerReducer } from 'react-router-redux';
import coursesIndex from './coursesIndexReducers';
import usersIndex from './usersIndexReducers';
import userData from './userDataReducers';
import report from './reportReducers';
import reportsList from './reportsListReducers';
import generalData from './generalDataReducers';

export default combineReducers({
  coursesIndex,
  usersIndex,
  userData,
  reportsList,
  report,
  generalData,
  routing: routerReducer
})
