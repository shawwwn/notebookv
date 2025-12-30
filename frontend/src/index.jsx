import { createSignal, lazy } from "solid-js";
import { render } from "solid-js/web";
import { Router, Route, Navigate } from "@solidjs/router";

import Main from "/src/main.jsx";
import Counter from "/src/counter";
import { NoteBookPage } from "/src/note";
import { SearchPage } from "/src/search";
import { Loader } from "/src/loader";
import { Login } from "/src/login";
import { DashboardPage } from "/src/dashboard";

// provides routing

render(
  () => (
    <Router>
      <Route path="/" component={Main} />
      <Route path="/login" component={Login} />
      <Route path="/counter" component={Counter} />
      <Route path="/note" component={() => <Navigate href="/note/1" />} />
      <Route path="/note/:notebookid/:noteid?" component={NoteBookPage} />
      <Route path="/note/:notebookid/search" component={SearchPage} />
      <Route path="/:username" component={DashboardPage} />
      <Route path="/loader" component={Loader} />
    </Router>
  ),
  document.getElementById("app")
);
