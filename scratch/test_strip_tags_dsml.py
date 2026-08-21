# -*- coding: utf-8 -*-
"""Test offline: kwadratowe znaczniki DSML / zamykajace tagi kontrolne w [ ].

Fix #8 (uzupelnienie): proxy wpuszczalo do chatu brud typu [/parameter],
[/|parameter], [|DSML|], [|DSML|parameter] bo:
  - _STRIP_TAGS lapal DSML tylko w nawiasach katowych </...>,
  - galez kwadratowa generate() (server.py ~3526) przepuszczala nieznane [ ... ].

Weryfikacja czysto offline: server._STRIP_TAGS.sub() na zbiorze testow.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server

BAR = "\uff5c"  # | - pelnowymiarowa pionowa kreska (znacznik DSML modelu)
FAILS = []


def check(label, text, expected_stripped):
    out = server._STRIP_TAGS.sub("", text)
    if expected_stripped:
        ok = out.strip() == ""
    else:
        ok = text in out
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label:45s} -> {out!r}")
    if not ok:
        FAILS.append(label)


def check_removed(label, text, removed_tag):
    """Tag musi zniknac, ale reszta tekstu zostaje."""
    out = server._STRIP_TAGS.sub("", text)
    ok = removed_tag not in out and out.strip() != ""
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label:45s} -> {out!r}")
    if not ok:
        FAILS.append(label)


def main():
    print("=" * 72)
    print("TEST _STRIP_TAGS — kwadratowe tagi DSML / kontrolne")
    print("=" * 72)

    print("\n-- POZYTYWNE (maja byc wylesione calkowicie) --")
    check("[/{BAR}{BAR}parameter]", f"[/{BAR}{BAR}parameter]", True)
    check("[{BAR}{BAR}DSML{BAR}{BAR}]", f"[{BAR}{BAR}DSML{BAR}{BAR}]", True)
    check("[{BAR}{BAR}DSML{BAR}{BAR}parameter]", f"[{BAR}{BAR}DSML{BAR}{BAR}parameter]", True)
    check("[/parameter]", "[/parameter]", True)
    check("[/{BAR}{BAR}parameter]", f"[/{BAR}{BAR}parameter]", True)
    check("[/DSML]", "[/DSML]", True)
    check_removed("[{BAR}{BAR}DSML{BAR}{BAR}] w srodku zdania",
                  f"Tekst [ {BAR}{BAR}DSML{BAR}{BAR}] koniec", f"[{BAR}{BAR}DSML{BAR}{BAR}]")
    check_removed("realny leak: _tmp_live_test.py[/{BAR}{BAR}parameter]",
                  f"_tmp_live_test.py[/{BAR}{BAR}parameter]", f"[/{BAR}{BAR}parameter]")
    check("istniejacy: [{call}Read]", f"[{server._CALL_MARKER}Read]", True)
    check("istniejacy: </cl_calls>", "</cl_calls>", True)
    check("istniejacy: <tool_call name=Read>", "<tool_call name=\"Read\">", True)

    print("\n-- NEGATYWNE (normalny tekst MUSI przetrwac) --")
    check("[bold]", "[bold]", False)
    check("[1]", "[1]", False)
    check("[link text](/url)", "[link text](/url)", False)
    check("[/home/user]", "[/home/user]", False)
    check("[/2026]", "[/2026]", False)
    check("[...]", "[...]", False)
    check("[Image: url]", "[Image: url]", False)
    check("[xyz nie zamkniety", "[xyz nie zamkniety", False)

    print("\n-- SPLIT-CHUNK: galez kwadratowa generate() trzyma '[/' (czeka na ']') --")
    hold_re = rf'\[\s*(?:{server._CALL_MARKER}|tool|/[|\uff5c\u2502\s]*[a-z]?|[a-zA-Z])'
    for frag, expect_hold in (("[/", True), ("[/" + BAR, True), ("[x", True),
                              ("[1", False), ("[ ", False), ("[", False)):
        got = bool(re.match(hold_re, frag))
        status = "PASS" if got == expect_hold else "FAIL"
        print(f"[{status}] hold({frag!r}) = {got} (oczekiwane {expect_hold})")
        if got != expect_hold:
            FAILS.append(f"hold({frag!r})")

    print("\n" + "=" * 72)
    if FAILS:
        print(f"WYNIK: FAIL — {len(FAILS)} niepowodzen: {FAILS}")
        sys.exit(1)
    print("WYNIK: WSZYSTKIE ASERCJE PRZESZLY")


if __name__ == "__main__":
    main()
