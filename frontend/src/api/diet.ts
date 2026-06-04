// API client for the CARA Nutrizione (diet) module.
//
// Router: /api/v1/diet. Auth via the shared authFetch. The plan reasons
// by WEEKLY FREQUENCIES of protein categories + raw portions; calories
// are a secondary metric. Disclaimer: reminders/suggestions only, not a
// medical device.

import { authFetch } from './auth';

const API = '/api/v1/diet';

export type FoodStatus = 'consigliato' | 'da_moderare' | 'sconsigliato';
export type ProteinCategory = 'legumi' | 'pesce' | 'carne' | 'uova' | 'formaggio';
export type MealType = 'colazione' | 'spuntino' | 'pranzo' | 'cena';
export type CategoryState = 'ok' | 'under' | 'over' | 'warn';

// Plan colors (from the PDF, page 12).
export const CATEGORY_COLOR: Record<ProteinCategory, string> = {
  legumi: '#22c55e', // verde
  pesce: '#38bdf8', // azzurro
  carne: '#d946ef', // magenta
  uova: '#3b82f6', // blu
  formaggio: '#eab308', // giallo
};

export const STATUS_LABEL: Record<FoodStatus, string> = {
  consigliato: 'Consigliato',
  da_moderare: 'Da moderare',
  sconsigliato: 'Sconsigliato',
};

export interface FoodItem {
  id: number;
  name: string;
  status: FoodStatus;
  protein_category: ProteinCategory | null;
  default_portion_g: number | null;
  portion_primo_g: number | null;
  portion_secondo_g: number | null;
  kcal_per_100g: number | null;
  season_months: number[] | null;
  notes: string | null;
}

export interface ParsedItem {
  food: string;
  portion_g: number | null;
  protein_category: ProteinCategory | null;
  status: FoodStatus | null;
  known?: boolean;
}

export interface MealLog {
  id: number;
  user_id: number;
  logged_at: string;
  meal_type: MealType;
  free_text: string | null;
  parsed_items: ParsedItem[];
  est_kcal: number | null;
  protein_category: ProteinCategory | null;
  context_flags: Record<string, boolean>;
}

export interface MealLogResult {
  log: MealLog;
  warnings: string[];
  carb_present: boolean;
  vegetable_present: boolean;
  fruit_present: boolean;
}

export interface TodayMealSlot {
  meal_type: MealType;
  done: boolean;
  logs: MealLog[];
}

export interface Today {
  day: string;
  slots: TodayMealSlot[];
  missing: MealType[];
  water_ml: number;
  water_target_min: number;
  water_target_max: number;
  coffee_count: number;
  coffee_max: number;
  fruit_servings: number;
  fruit_target_min: number;
}

export interface CategoryProgress {
  category: ProteinCategory;
  color: string;
  consumed: number;
  target_min: number | null;
  target_max: number | null;
  state: CategoryState;
}

export interface Week {
  week_start: string;
  week_end: string;
  categories: CategoryProgress[];
  adherence_score: number;
  avg_kcal_per_day: number | null;
  avg_water_ml: number | null;
  avg_coffee: number | null;
  notes: string[];
}

export interface DishSuggestion {
  title: string;
  covers_category: ProteinCategory | null;
  detail: string;
}

export interface Suggest {
  meal_type: MealType;
  suggestions: DishSuggestion[];
  under_target: ProteinCategory[];
  warnings: string[];
  context_reminders: string[];
  speak_text: string;
}

export interface DietRule {
  id: number;
  plan_id: number;
  category: string;
  target_min: number | null;
  target_max: number | null;
  period: string | null;
  portion_primo_g: number | null;
  portion_secondo_g: number | null;
  portion_note: string | null;
  kcal_estimate: number | null;
}

export interface Recipe {
  id: number;
  name: string;
  ingredients: { item: string; qty: string }[];
  steps: string | null;
  source: string | null;
}

export interface Intake {
  day: string;
  water_ml: number;
  coffee_count: number;
}

export interface WeeklyReport {
  week_start: string;
  week_end: string;
  pdf_url: string | null;
  telegram_text: string;
  sent_to_telegram: boolean;
}

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const detail = await r
      .json()
      .then((j) => j.detail)
      .catch(() => `HTTP ${r.status}`);
    throw new Error(typeof detail === 'string' ? detail : `HTTP ${r.status}`);
  }
  return r.json();
}

export async function logMeal(payload: {
  free_text: string;
  meal_type?: MealType;
}): Promise<MealLogResult> {
  return json(
    await authFetch(`${API}/log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  );
}

// ─── Barcode (Open Food Facts) ─────────────────────────────────────

export interface BarcodeProduct {
  barcode: string;
  name: string;
  brand: string | null;
  quantity: string | null;
  kcal_per_100g: number | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
  nutriscore: string | null; // a..e
  image_url: string | null;
  from_cache: boolean;
}

/** Resolve a scanned barcode. Throws "Prodotto non trovato" on 404. */
export async function lookupBarcode(code: string): Promise<BarcodeProduct> {
  return json(await authFetch(`${API}/barcode/${encodeURIComponent(code)}`));
}

/** Log a scanned product as a meal (kcal computed from portion). */
export async function logBarcode(payload: {
  barcode: string;
  portion_g: number;
  meal_type?: MealType;
}): Promise<MealLog> {
  return json(
    await authFetch(`${API}/barcode/log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  );
}

// ─── "Cosa cucino?" — piatti dalla spesa ───────────────────────────

export interface DishIngredient {
  name: string;
  portion_g: number | null;
  kcal: number | null;
  have: boolean;
  status: FoodStatus | null;
}

export interface DishProposal {
  slug: string;
  title: string;
  covers_category: ProteinCategory | null;
  kcal_estimate: number | null;
  ingredients: DishIngredient[];
  missing: string[];
  note: string | null;
}

export interface RecipeDetail {
  name: string;
  ingredients: { item: string; qty: string | null }[];
  steps: string | null;
  source: string | null;
}

export async function getDishes(meal: MealType = 'cena'): Promise<DishProposal[]> {
  return json(await authFetch(`${API}/dishes?meal=${meal}`));
}

export async function getDishRecipe(title: string): Promise<RecipeDetail> {
  return json(await authFetch(`${API}/dishes/recipe?title=${encodeURIComponent(title)}`));
}

export async function addDishMissingToShopping(names: string[]): Promise<{ added: number }> {
  return json(
    await authFetch(`${API}/dishes/shopping`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ names }),
    }),
  );
}

export async function getToday(): Promise<Today> {
  return json(await authFetch(`${API}/today`));
}

export interface HistoryDay {
  day: string;
  meals: MealLog[];
  total_kcal: number | null;
}

export interface History {
  days: HistoryDay[];
}

/** Pasti registrati negli ultimi `days` giorni, raggruppati per giorno. */
export async function getHistory(days = 14): Promise<History> {
  return json(await authFetch(`${API}/history?days=${days}`));
}

/** Modifica un pasto: sposta lo slot e/o riscrivi il testo. */
export async function updateMeal(
  id: number,
  patch: { meal_type?: MealType; free_text?: string },
): Promise<MealLogResult> {
  return json(
    await authFetch(`${API}/meal/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  );
}

/** Elimina un pasto registrato. */
export async function deleteMeal(id: number): Promise<void> {
  const r = await authFetch(`${API}/meal/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export async function getWeek(anchor?: string): Promise<Week> {
  const q = anchor ? `?anchor=${anchor}` : '';
  return json(await authFetch(`${API}/week${q}`));
}

export async function getSuggest(meal: MealType = 'cena'): Promise<Suggest> {
  return json(await authFetch(`${API}/suggest?meal=${meal}`));
}

export async function getFoods(opts?: {
  status?: FoodStatus;
  category?: ProteinCategory;
  q?: string;
}): Promise<FoodItem[]> {
  const p = new URLSearchParams();
  if (opts?.status) p.set('status', opts.status);
  if (opts?.category) p.set('category', opts.category);
  if (opts?.q) p.set('q', opts.q);
  return json(await authFetch(`${API}/foods?${p.toString()}`));
}

export async function getRecipes(): Promise<Recipe[]> {
  return json(await authFetch(`${API}/recipes`));
}

export async function getRules(): Promise<DietRule[]> {
  return json(await authFetch(`${API}/rules`));
}

export async function updateRule(id: number, patch: Partial<DietRule>): Promise<DietRule> {
  return json(
    await authFetch(`${API}/rules/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  );
}

export async function addWater(ml = 250): Promise<Intake> {
  return json(
    await authFetch(`${API}/water`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ml }),
    }),
  );
}

export async function addCoffee(count = 1): Promise<Intake> {
  return json(
    await authFetch(`${API}/coffee`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count }),
    }),
  );
}

export async function generateWeeklyReport(opts?: {
  shareTelegram?: boolean;
  anchor?: string;
}): Promise<WeeklyReport> {
  const p = new URLSearchParams();
  if (opts?.shareTelegram) p.set('share_telegram', 'true');
  if (opts?.anchor) p.set('anchor', opts.anchor);
  return json(await authFetch(`${API}/report/weekly?${p.toString()}`, { method: 'POST' }));
}

// ─── Energy: profile / exercise / stats ────────────────────────────

export type ActivityLevel = 'sedentary' | 'light' | 'moderate' | 'very' | 'extra';
export type Goal = 'maintain' | 'lose' | 'gain';
export type EnergyPeriod = 'day' | 'week' | 'month' | 'year';

export interface DietProfile {
  sex: 'M' | 'F' | null;
  birth_date: string | null;
  height_cm: number | null;
  weight_kg: number | null;
  activity_level: ActivityLevel;
  goal: Goal;
  goal_rate_kcal: number | null;
  age: number | null;
  bmr: number | null;
  tdee: number | null;
  daily_target: number | null;
  complete: boolean;
}

export interface MetActivity {
  slug: string;
  label: string;
  met: number;
  intensity: string;
}

export interface ExerciseLog {
  id: number;
  user_id: number;
  logged_at: string;
  activity: string;
  met: number;
  duration_min: number;
  kcal_burned: number;
  notes: string | null;
}

export interface EnergyBucket {
  label: string;
  start: string;
  consumed: number;
  burned: number;
  target: number | null;
}

export interface EnergyStats {
  period: EnergyPeriod;
  period_start: string;
  period_end: string;
  profile_complete: boolean;
  bmr: number | null;
  tdee: number | null;
  daily_target: number | null;
  days_elapsed: number;
  consumed: number;
  burned: number;
  net: number;
  target_total: number | null;
  remaining: number | null;
  avg_consumed_per_day: number;
  avg_burned_per_day: number;
  breakdown: EnergyBucket[];
}

export const ACTIVITY_LABEL: Record<ActivityLevel, string> = {
  sedentary: 'Sedentario',
  light: 'Leggermente attivo',
  moderate: 'Moderatamente attivo',
  very: 'Molto attivo',
  extra: 'Estremamente attivo',
};

export const GOAL_LABEL: Record<Goal, string> = {
  maintain: 'Mantenere il peso',
  lose: 'Perdere peso',
  gain: 'Aumentare di peso',
};

export const PERIOD_LABEL: Record<EnergyPeriod, string> = {
  day: 'Giorno',
  week: 'Settimana',
  month: 'Mese',
  year: 'Anno',
};

export async function getProfile(): Promise<DietProfile> {
  return json(await authFetch(`${API}/profile`));
}

export async function putProfile(patch: Partial<DietProfile>): Promise<DietProfile> {
  return json(
    await authFetch(`${API}/profile`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  );
}

export async function getEnergy(period: EnergyPeriod = 'day'): Promise<EnergyStats> {
  return json(await authFetch(`${API}/energy?period=${period}`));
}

export async function getExerciseCatalog(): Promise<MetActivity[]> {
  return json(await authFetch(`${API}/exercise/catalog`));
}

export async function listExercise(day?: string): Promise<ExerciseLog[]> {
  const q = day ? `?day=${day}` : '';
  return json(await authFetch(`${API}/exercise${q}`));
}

export async function addExercise(payload: {
  activity: string;
  slug?: string;
  met?: number;
  duration_min: number;
  notes?: string;
}): Promise<ExerciseLog> {
  return json(
    await authFetch(`${API}/exercise`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  );
}

export async function deleteExercise(id: number): Promise<void> {
  const r = await authFetch(`${API}/exercise/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}

export const DISCLAIMER =
  'Promemoria e suggerimenti, non un dispositivo medico. La fonte è il piano ' +
  'della Dott.ssa Elena Poletti; per dubbi rivolgersi a lei.';

export const MEAL_LABEL: Record<MealType, string> = {
  colazione: 'Colazione',
  spuntino: 'Spuntino',
  pranzo: 'Pranzo',
  cena: 'Cena',
};
