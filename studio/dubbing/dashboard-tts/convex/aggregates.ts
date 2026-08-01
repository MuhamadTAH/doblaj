import { components } from "./_generated/api";
import { DataModel } from "./_generated/dataModel";
import { Aggregate } from "@convex-dev/aggregate";

export const semanticRatioAggregate = new Aggregate<DataModel>({
  name: "semanticRatio",
  aggregate: {
    sum: (doc) => doc.semantic_ratio ?? 0,
    count: (doc) => 1,
  },
  filter: (doc) => {
    // Only include non-clamped chunks with a valid semantic_ratio and speed_multiplier roughly 1.0
    if (doc.was_clamped) return false;
    if (doc.semantic_ratio === undefined || doc.semantic_ratio === null) return false;
    if (doc.speed_multiplier === undefined || doc.speed_multiplier === null) return false;
    
    // Only include rows where speed_multiplier is between 0.9 and 1.1
    if (doc.speed_multiplier < 0.9 || doc.speed_multiplier > 1.1) return false;
    
    return true;
  },
});
