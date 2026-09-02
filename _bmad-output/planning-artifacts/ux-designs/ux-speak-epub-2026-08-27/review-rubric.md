# Spine Pair Review — speak epub

## Overall verdict
Spine merytorycznie domknięty dla v1 hobby — pokrywa cały flow URL/title → EPUB/M4B, zachowuje politykę polite i progressive disclosure. Ryzyko downstream niskie; brak mocków przed finalize jest główną luką wizualną, ale celowo odłożoną na fast path. Po dodaniu 2–3 key-screenów spine gotowy do architektury.

## 1. Flow coverage — adequate
Checked: brief.md 6 kroków (Find, Choose, Fetch & clean, Build EPUB, Make audio, Control) + addendum constraints. EXPERIENCE.md ma 2 named-protagonist flows (Marta reader-first, Jan listener) z numeracją i climax.

### Findings
- **[medium]** Każdy krok briefu powinien mieć failure path gdzie dotyczy (np. 429/ban w Marta flow tylko wspomniane marginalnie). *Fix:* w Marta kroku 5 dopisać gałąź „jeśli 429 → toast safe mode, kontynuuje; jeśli ban → pauza z resume hint” — 1 zdanie wystarczy.
- **[low]** Brak jednej podróży dla „wznów po błędzie” jako osobnej flow (resume conditional bounded vs open-ended). *Fix:* dopisać 2 zdania w Jan kroku 6 lub dodać trzeci micro-flow „Wznów” — opcjonalne dla v1.

## 2. Token completeness — strong
Checked: DESIGN.md frontmatter tokens (colors 15 incl. dark pairs, typography 6 roles, rounded 5, spacing 6, components 5) i wszystkie {path.to.token} w prose ( {colors.primary}, {colors.accent}, {colors.muted}, {colors.ring}, {colors.success}, {colors.warning}, {typography.display-sm}, {rounded.md} itp.). Wszystkie resolwują; hex kompletny; dark pairs obecne.

### Findings
- **[low]** \{typography.body-sm}\ i \{spacing.lg}\ zdefiniowane ale nie referencjonowane — nie błąd, tylko niewykorzystany sygnał do arch. *Fix:* brak; opcjonalnie dodać 1 cross-ref w EXPERIENCE Settings helper.

## 3. Component coverage — adequate
Checked: komponenty w obu spine’ach. DESIGN: Input, Search result row, Chapter table, Button primary/accent, Progress row, Preview tabs, Filter chip, Settings group, Toast. EXPERIENCE: Find input, Results table, Range bar, Chapter table, Preview split, Queue list, Output cards, Settings form, Filters table.

### Findings
- **[medium]** Nazwy nie identyczne między spine’ami (np. „Search result row” vs „Results table”, „Button primary” bez pary behawioralnej, „Range bar” bez pary wizualnej). Downstream musi zgadywać. *Fix:* ujednolicić słownik: dodać w DESIGN.md „Range bar” i „Queue list” jako sekcje, w EXPERIENCE dodać regułę dla „Button primary” (kiedy ink vs accent) — 2–3 wiersze każdy.

## 4. State coverage — strong
Checked: 7 IA surfaces walk (Find, Chapters, Preview, Queue, Result, Settings, Filters). Pokryte: cold launch, searching, no results, loading, 429/throttled, ban, empty preview, offline, build done, persisted, FFmpeg missing.

### Findings
- **[low]** Brak stanu „permission-denied” nie ma zastosowania (local-only) — poprawnie pominięte, odnotować w tabeli jako N/A by audytor nie szukał.

## 5. Visual reference coverage — thin
Checked: \.working/\, \imports/\, \mockups/\, \wireframes/\ — na moment review puste (fast path). Spines nie linkują do plików; „Spines win on conflict” zdanie jest, ale bez inline linków.

### Findings
- **[high]** Brak wizualnych odniesień dla powierzchni, gdzie layout napędza zachowanie (Preview split 40/60, Queue per-part). *Fix:* wygenerować 2–3 key-screen HTML do \.working/\ → promować do \mockups/\ i dodać linki inline w EXPERIENCE IA (np. \mockups/find.html\). Zrobione w finalize po Twojej zgodzie — ten finding zniknie po dodaniu mocków.

## 6. Bloat & overspecification — strong
Checked: gęstość prose vs tabele. Oba spiny używają tabel dla Component/State/IA; brak restatement person z briefu; DESIGN dopuszcza editorial voice, EXPERIENCE trzyma dyscyplinę. Brak pixel-spec poza tokenami.

### Findings
- Brak — czysty fast path.

## 7. Inheritance discipline — adequate
Checked: frontmatter \sources\ resolwują (2 pliki), UJ-nazwy przejęte jako kroki briefu (Find/Choose/Fetch...), token refs resolwują, słownik komponentów 80% spójny (patrz §3).

### Findings
- **[low]** „Chapter table” występuje w obu, ale „Chapter list” vs „Chapters” surface naming w IA vs State — wybierz jedną formę. *Fix:* rename IA surface „Chapters” → „Chapter List” lub odwrotnie.

## 8. Shape fit — strong
Checked: DESIGN kolejność kanoniczna zachowana (8 sekcji, omittable none, order locked) — ok. EXPERIENCE ma wszystkie required defaults (Foundation, IA, Voice and Tone, Component Patterns, State Patterns, Interaction Primitives, Accessibility Floor, Key Flows) + triggered Responsive & Platform oraz Inspiration & Anti-patterns gdzie brief pokazuje rejects — poprawnie.

### Findings
- Brak.

## Mechanical notes
- Frontmatter kompletny (name, description, status draft, sources, updated, tokens). Mermaid nie używany — brak do sprawdzenia. Cross-refs \.working/\ brak orphanów (puste). Podmiana „Chapters” naming ujednolici mechanikę.
