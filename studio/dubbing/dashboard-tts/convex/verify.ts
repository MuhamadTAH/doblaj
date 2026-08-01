import { internalQuery } from "./_generated/server";

export const sampleJobs = internalQuery({
  args: {},
  handler: async (ctx) => {
    const rows = await ctx.db.query("dubbingJobs").collect();
    return rows.slice(0, 20).map((j) => ({
      _id: j._id,
      legacyId: j.legacyId,
      workspaceId: j.workspaceId,
      status: j.status,
      workspaceIsId: typeof j.workspaceId === "string" ? false : true,
    }));
  },
});


