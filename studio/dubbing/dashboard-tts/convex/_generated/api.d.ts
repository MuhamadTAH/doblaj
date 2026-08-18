/* eslint-disable */
/**
 * Generated `api` utility.
 *
 * THIS CODE IS AUTOMATICALLY GENERATED.
 *
 * To regenerate, run `npx convex dev`.
 * @module
 */

import type * as admin from "../admin.js";
import type * as adminQuery from "../adminQuery.js";
import type * as adminTasks from "../adminTasks.js";
import type * as aggregates from "../aggregates.js";
import type * as baseline from "../baseline.js";
import type * as consents from "../consents.js";
import type * as crons from "../crons.js";
import type * as debugJobs from "../debugJobs.js";
import type * as debugWorkspaces from "../debugWorkspaces.js";
import type * as dictionaries from "../dictionaries.js";
import type * as dubbingChunks from "../dubbingChunks.js";
import type * as dubbingJobs from "../dubbingJobs.js";
import type * as http from "../http.js";
import type * as lib_auth from "../lib/auth.js";
import type * as payments from "../payments.js";
import type * as relink from "../relink.js";
import type * as seedVoices from "../seedVoices.js";
import type * as stepTelemetry from "../stepTelemetry.js";
import type * as sweeper from "../sweeper.js";
import type * as tempQuery from "../tempQuery.js";
import type * as transactions from "../transactions.js";
import type * as usageLogs from "../usageLogs.js";
import type * as users from "../users.js";
import type * as verify from "../verify.js";
import type * as voices from "../voices.js";
import type * as webhooks from "../webhooks.js";
import type * as workspaces from "../workspaces.js";

import type {
  ApiFromModules,
  FilterApi,
  FunctionReference,
} from "convex/server";

declare const fullApi: ApiFromModules<{
  admin: typeof admin;
  adminQuery: typeof adminQuery;
  adminTasks: typeof adminTasks;
  aggregates: typeof aggregates;
  baseline: typeof baseline;
  consents: typeof consents;
  crons: typeof crons;
  debugJobs: typeof debugJobs;
  debugWorkspaces: typeof debugWorkspaces;
  dictionaries: typeof dictionaries;
  dubbingChunks: typeof dubbingChunks;
  dubbingJobs: typeof dubbingJobs;
  http: typeof http;
  "lib/auth": typeof lib_auth;
  payments: typeof payments;
  relink: typeof relink;
  seedVoices: typeof seedVoices;
  stepTelemetry: typeof stepTelemetry;
  sweeper: typeof sweeper;
  tempQuery: typeof tempQuery;
  transactions: typeof transactions;
  usageLogs: typeof usageLogs;
  users: typeof users;
  verify: typeof verify;
  voices: typeof voices;
  webhooks: typeof webhooks;
  workspaces: typeof workspaces;
}>;

/**
 * A utility for referencing Convex functions in your app's public API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = api.myModule.myFunction;
 * ```
 */
export declare const api: FilterApi<
  typeof fullApi,
  FunctionReference<any, "public">
>;

/**
 * A utility for referencing Convex functions in your app's internal API.
 *
 * Usage:
 * ```js
 * const myFunctionReference = internal.myModule.myFunction;
 * ```
 */
export declare const internal: FilterApi<
  typeof fullApi,
  FunctionReference<any, "internal">
>;

export declare const components: {};
