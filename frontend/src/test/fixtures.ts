import type { Option, Quote } from "../types";

const line = (group: string, total: number) => ({ group, sku: group.toUpperCase(), name: `${group} item`, tier: "standard", unit: "sqft", quantity: 10, unit_price: 100, material_cost: total - 100, labor_trade: "carpenter", labor_hours: 1, labor_cost: 100, line_total: total, optional: group === "backsplash", lead_days: 5 });
const opt = (label: string, total: number): Option => ({
  tier_label: label, lines: [line("kitchen_cabinets", 5000), line("backsplash", 1500)], materials_subtotal: 6000, labor_subtotal: 500, logistics: 180, subtotal: 6680, contingency: 534, tax: 1298, total,
  currency: "INR", warnings: [], timeline: { weeks: 5.5, working_days: 33, phases: [], critical_material: "Acrylic modular unit" },
  params: { region: "chennai", region_multiplier: 0.98, complexity: "standard", contingency_pct: 8, logistics_pct: 3, tax_pct: 18 },
});
export const quote: Quote = {
  id: "q1", project_id: "p1", version: 2, parent_version: 1, reason: "negotiation", status: "pending_approval", selected_tier: "standard", currency: "INR", total: 8512, confidence: 0.82, created_at: "2026-10-06T00:00:00Z",
  payload: {
    category: "kitchen_renovation", category_label: "Kitchen renovation",
    options: { budget: opt("budget", 5000), standard: opt("standard", 8512), premium: opt("premium", 12000) },
    narrative: { summary: "Standard option estimated pending a site survey." }, assumptions: ["Area assumed from photo"], exclusions: ["Appliances"], risks: [], tradeoffs: ["Backsplash dropped"],
    validation: { flags: [{ code: "area_assumed", severity: "high", blocking: true, message: "Floor area was assumed." }], confidence: 0.82, approval_reasons: [] },
    evidence: [], negotiation: null, recommendations: [], disclaimer: "Estimate only.", ai: { provider: "mock", mock: true, models: {} },
  },
};
