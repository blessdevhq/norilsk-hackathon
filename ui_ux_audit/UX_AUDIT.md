# UI/UX audit: unclear points for end users

Scope: current React/Vite UI at `http://127.0.0.1:5173`, checked on July 5, 2026.

Screenshots:

- `01-overview.png` - overview with answer and related experiments.
- `02-graph.png` - knowledge graph.
- `03-matrix.png` - gap matrix.
- `04-evidence.png` - sources and evidence.
- `05-geo-conflicts.png` - geography and contradictions.
- `06-entities.png` - graph entities.
- `07-mobile-loading.png` - mobile loading state.
- `08-mobile-overview-loaded.png` - mobile loaded overview.

## Step health

1. Overview: usable and much clearer than a demo board, but the product promise and query model still need one more explicit sentence.
2. Graph: visually coherent, but node/edge meaning and click outcome are not self-explanatory enough for a first-time user.
3. Matrix: valuable differentiator, but legend thresholds and cell behavior are unclear.
4. Sources: evidence is visible and traceable, but repeated technical labels can look like missing data or system noise.
5. Geo/conflicts: useful risk view, but "contradiction" needs a plain-language criterion so it is not read as a product error.
6. Entities: compact and scannable, but counts lack context and expert/person/organization types are mixed visually.
7. Mobile: no horizontal overflow after loading, but loading state briefly shows zero metrics and an empty-answer message that can look like failure.

## Main unclear points

1. First-time user may not immediately understand what the product is.
   Evidence: `01-overview.png`. The screen says "Проверяемый ответ", but does not explicitly say "this is a fact-traced R&D knowledge graph over documents, not a generic chat/search".
   Minimal fix: add a one-line product statement under the title or near the search bar.

2. Query format is still under-explained.
   Evidence: `01-overview.png`, `08-mobile-overview-loaded.png`. Search is primary, but examples/presets are not visible in the first desktop viewport and are below the fold on mobile.
   Minimal fix: add 2-3 small example chips directly under the search input or a "Можно спросить так..." hint.

3. The 82% confidence ring can be misread as model accuracy or truth score.
   Evidence: `01-overview.png`, `08-mobile-overview-loaded.png`.
   Minimal fix: rename or tooltip it as "доля фактов с высокой/средней достоверностью" or whatever exact calculation is used.

4. "Проверяемо" and "Авто-извлечение" can sound more final than the data actually is.
   Evidence: `01-overview.png`, `04-evidence.png`. The answer correctly says expert verification is required, but the badges are stronger than the caveat.
   Minimal fix: use "Трассируемо" or add "требует экспертной проверки" beside the verification badge.

5. Related experiment cards expose internal system language.
   Evidence: `01-overview.png`. IDs like `E-0001`, truncated source names, and the action "уточнить по этому факту" may be unclear to non-technical users.
   Minimal fix: title the block as "Факты-основания" and make the action explicit: "Собрать ответ по этому материалу/процессу".

6. Matrix legend lacks thresholds.
   Evidence: `03-matrix.png`. "Единичные данные", "частично изучено", and "изучено много" are useful labels, but users do not know the count ranges.
   Minimal fix: show ranges in legend, for example `0`, `1-2`, `3-10`, `10+` if those are the true thresholds.

7. Clicking a matrix cell changes the answer, but this relation is easy to miss.
   Evidence: `03-matrix.png`. Instruction exists, but the interaction is not reinforced after selection.
   Minimal fix: after click, show a sticky context chip like "Выбран пробел: шлак x электроэкстракция" with a return link to the matrix.

8. Graph interaction does not provide enough local feedback.
   Evidence: `02-graph.png`. The graph is readable visually, but edge labels are small and there is no visible details panel in the initial viewport.
   Minimal fix: add a right-side "Выбранный узел/связь" panel or stronger hover/click feedback.

9. "Потенциальные противоречия" may be interpreted as data errors.
   Evidence: `05-geo-conflicts.png`.
   Minimal fix: add one sentence explaining that these are differences in reported values, contexts, or effect directions that need expert review.

10. "Условия не выделены" appears repeatedly and can look like a defect.
    Evidence: `04-evidence.png`.
    Minimal fix: make it softer, for example "условия в источнике не распознаны", or move it into secondary metadata.

11. Entity counts need definitions.
    Evidence: `06-entities.png`. "Эксперты" mixes people, organizations, departments, and possibly roles.
    Minimal fix: split or label entity types more clearly: people, organizations, departments, source authors.

12. Mobile loading state can be confusing.
    Evidence: `07-mobile-loading.png`. The page shows "Ищу...", disabled export, `0%`, and "Выберите запрос..." at the same time.
    Minimal fix: during loading, replace empty-answer text with one status block and hide zero-state metrics until the response arrives.

## Accessibility and verification limits

- Confirmed from screenshots: responsive layout has no visible horizontal overflow on the loaded mobile screen.
- Likely risk: matrix state relies heavily on color, even though numbers help.
- Likely risk: graph labels and edge labels can be too small for low-vision users.
- Likely risk: truncated query/source text hides context; keyboard and screen reader behavior were not fully tested from screenshots alone.
- Positive code signal from inspection: navigation uses `aria-current`, query input has an `aria-label`, and API errors use `role="alert"`.
