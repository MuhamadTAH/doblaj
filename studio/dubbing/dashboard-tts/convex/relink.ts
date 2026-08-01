import { internalMutation } from "./_generated/server";
import { Id } from "./_generated/dataModel";

export const relinkWorkspaceRefs = internalMutation({
  args: {},
  handler: async (ctx) => {
    const workspaces = await ctx.db.query("workspaces").collect();
    const legacyToId = new Map<string, Id<"workspaces">>();
    for (const ws of workspaces) {
      legacyToId.set(ws.legacyId, ws._id);
    }

    const members = await ctx.db.query("workspaceMembers").collect();
    let membersFixed = 0;
    for (const m of members) {
      if (typeof m.workspaceId === "string") {
        const target = legacyToId.get(m.workspaceId);
        if (!target) throw new Error(`Missing workspace ${m.workspaceId}`);
        await ctx.db.patch(m._id, { workspaceId: target });
        membersFixed += 1;
      }
    }

    const jobs = await ctx.db.query("dubbingJobs").collect();
    let jobsFixed = 0;
    for (const j of jobs) {
      if (typeof j.workspaceId === "string") {
        const target = legacyToId.get(j.workspaceId);
        if (!target) throw new Error(`Missing workspace ${j.workspaceId}`);
        await ctx.db.patch(j._id, { workspaceId: target });
        jobsFixed += 1;
      }
    }

    return { membersFixed, jobsFixed };
  },
});
