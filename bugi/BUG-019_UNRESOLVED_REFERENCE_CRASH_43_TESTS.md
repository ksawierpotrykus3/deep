# BUG-019: Złamanie Kompilacji TypeScript i Wysypanie 43 Testów przez Brak Wywołania `useLiveTracking` w `NotesCanvas.tsx`

**Data rejestracji:** 2026-09-01 15:56  
**Komponenty:** `cortex-app` (`NotesCanvas.tsx`, `src/components/canvas/useLiveTracking.ts`), Vitest Test Suite, Trae Panic Loop  
**Wpływ na działanie:** KRYTYCZNY (Błąd kompilacji `TS2304`, runtime `ReferenceError: liveTrackingEnabled is not defined`, 43 z 63 testów wywalone na czerwono, agent wpadł w pętlę 8-krotnego czytania `NotesCanvas.tsx`).

---

## 1. DOWODY EMPIRYCZNE (Objawy z terminala i ze zrzutu ekranu)

### Incydent 1: Błąd kompilacji TypeScript (`npx tsc --noEmit`)
```text
src/components/NotesCanvas.tsx(2190,30): error TS2304: Cannot find name 'liveTrackingEnabled'.
src/components/NotesCanvas.tsx(2191,33): error TS2304: Cannot find name 'setLiveTrackingEnabled'.
```

### Incydent 2: Masowa awaria testów jednostkowych (`npm test`)
```text
FAIL src/components/NotesCanvas.test.tsx
ReferenceError: liveTrackingEnabled is not defined
 ❯ NotesCanvas src/components/NotesCanvas.tsx:2190:9
    2189| setShowHelp={setShowHelp}
    2190| liveTrackingEnabled={liveTrackingEnabled}
        | ^
    2191| setLiveTrackingEnabled={setLiveTrackingEnabled}

Test Files: 1 failed | 1 passed (2)
Tests:      43 failed | 20 passed (63)
```

### Incydent 3: Pętla paniki w Trae (ze zrzutu ekranu użytkownika)
* `Failed to read useLiveTracking.ts`
* `Reading NotesCanvas.tsx` x8
* `Editing` x4
* `Searching liveTracking|useLiveTracking|Live Tracking`
Agent zorientował się, że coś zepsuł, i w panice zaczął czytać `NotesCanvas.tsx` 8 razy z rzędu.

---

## 2. PRZYCZYNY ŹRÓDŁOWE (Root Cause Analysis)

### A. Przekazanie nieistniejących zmiennych do propsów `CanvasHeader`
W pliku `src/components/NotesCanvas.tsx` na linii 2190 agent dopisał:
```tsx
liveTrackingEnabled={liveTrackingEnabled}
setLiveTrackingEnabled={setLiveTrackingEnabled}
```
Jednak zapomniał zaimportować i wywołać hooka:
```tsx
import { useLiveTracking } from './canvas/useLiveTracking';
// ...
const { liveTrackingEnabled, setLiveTrackingEnabled } = useLiveTracking({ ... });
```
Przez to zmienne nie istniały w zasięgu funkcji, wywołując `ReferenceError` przy próbie renderowania komponentu.

---

## 3. DETERMINISTYCZNY PLAN NAPRAWY

Naprawa wymaga:
1. Zaimportowania `useLiveTracking` w `NotesCanvas.tsx`,
2. Wywołania hooka z odpowiednimi referencjami (`activeProjectIdRef`, `offsetRef`, `scaleRef`, `selectedIdsRef`),
3. Uruchomienia `npm test` i potwierdzenia powrotu wszystkich 63 testów na zielono.
