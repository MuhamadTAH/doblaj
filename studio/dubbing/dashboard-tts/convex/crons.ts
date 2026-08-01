import { cronJobs } from "convex/server";
import { internal } from "./_generated/api";

const crons = cronJobs();

// Run every night at midnight to recalculate baseline
crons.daily(
  "recalculate-kurdish-baseline",
  { hourUTC: 0, minuteUTC: 0 },
  internal.baseline.updateBaseline
);

export default crons;
