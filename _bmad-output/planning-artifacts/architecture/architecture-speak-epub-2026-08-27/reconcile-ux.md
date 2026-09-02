# Reconcile — UX DESIGN.md / EXPERIENCE.md vs spine

- Design tokens (Inter, neutral+accent #2B5CE6) -> Stack Frontend Tailwind shadcn recommendation, no AD needed
- IA 7 surfaces Find/ChapterList/Preview/Queue/Result/Settings/Filters -> mapped in Capability Map
- Progressive disclosure -> AD-5 stateless GUI + AD-10 persisted config not on first screen
- Preview split 40/60 -> AD-7
- Queue per chapter/part + logs -> AD-6 event bus + AD-8 PartJob ratification
- Voice/rate/parallel/chunk/retries/delay/keeps -> AD-10

No UX behavior orphaned.
