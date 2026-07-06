// Code-based route tree (no file-based plugin). The root renders the three-pane
// shell; each child route selects the stream shown in the list pane. Params are
// strings, so feed/folder ids are parsed to numbers for the descriptor.

import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";

import { AppLayout } from "../features/layout/AppLayout";
import { StreamView } from "../features/stream/StreamView";

const rootRoute = createRootRoute({ component: AppLayout });

const allRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: function AllStream() {
    return <StreamView stream={{ kind: "all" }} />;
  },
});

const starredRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/starred",
  component: function StarredStream() {
    return <StreamView stream={{ kind: "starred" }} />;
  },
});

const feedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/feed/$id",
  component: function FeedStream() {
    const { id } = feedRoute.useParams();
    return <StreamView stream={{ kind: "feed", id: Number(id) }} />;
  },
});

const folderRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/folder/$id",
  component: function FolderStream() {
    const { id } = folderRoute.useParams();
    return <StreamView stream={{ kind: "folder", id: Number(id) }} />;
  },
});

const routeTree = rootRoute.addChildren([allRoute, starredRoute, feedRoute, folderRoute]);

export const router = createRouter({ routeTree, defaultPreload: "intent" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
