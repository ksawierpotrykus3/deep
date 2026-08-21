Rozmowa z Gemini
Treść Twojej wiadomości

Kompleksowa analiza architektury i fizyki tranzystorów GAAFET (Nanosheet / MBCFET) w węzłach 2nm i 1.4nm (TSMC N2/A16, Intel 18A/14A, Samsung SF2/SF1.4) z uwzględnieniem zasilania od spodu (Backside Power Delivery Network - PowerVia / BSPDN) oraz zjawisk termicznych (Self-Heating Effect)

Treść wiadomości Gemini

Oto, jak planuję podejść do tego zagadnienia. Jeśli chcesz, abym wprowadził zmiany, poinformuj mnie o tym.

 Analiza Architektury i Fizyki GAAFET 
Przeszukuj strony internetowe
(1) Zbadaj podstawy fizyki i geometrii tranzystorów GAAFET (Nanosheet / MBCFET), ze szczególnym uwzględnieniem elektrostatyki, sterowania kanałem, redukcji prądów upływu oraz przewag nad technologią FinFET.
(2) Przeanalizuj specyfikację i architekturę tranzystorów w nadchodzących węzłach technologicznych 2nm i 1.4nm:
(a) TSMC: procesy N2, N2P oraz A16
(b) Intel: procesy Intel 18A oraz Intel 14A (architektura RibbonFET)
(c) Samsung Foundry: procesy SF2 oraz SF1.4 (architektura MBCFET)
(3) Przebadaj technologie zasilania od spodu (Backside Power Delivery Network - BSPDN, PowerVia, Super PowerRail):
(a) zasada działania, architektura połączeń oraz korzyści (redukcja spadków napięcia IR drop, poprawa gęstości komórek, odciążenie warstw sygnałowych)
(b) wyzwania produkcyjne (szlifowanie wafli, klastry mikro- / nano-TSV, integracja ukrytych szyn zasilających)
(4) Przeanalizuj fizykę i skutki zjawiska samonagrzewania (Self-Heating Effect - SHE) w strukturach nanosheet:
(a) mechanizmy uwięzienia ciepła spowodowane izolacją tlenkową i skróconą drogą odprowadzania ciepła
(b) interakcję termiczną pomiędzy szynami BSPDN a strukturą tranzystora
(c) wpływ wzrostu temperatury na niezawodność, elektromigrację i degradację ruchliwości nośników
(5) Zsyntetyzuj zebrane dane, dokonując porównania rozwiązań TSMC, Intela i Samsunga pod kątem wydajności, efektywności energetycznej, zarządzania ciepłem oraz wyzwań skalowania w obszarze sub-2nm.
Więcej
Analizuj wyniki
Utwórz raport
Za kilka minut wszystko będzie gotowe
 Edytuj plan 
 Zacznij wyszukiwanie 
Treść Twojej wiadomości

Zacznij wyszukiwanie

Treść wiadomości Gemini

I've completed your research. Feel free to ask me follow-up questions or request changes.

Analiza Architektury i Fizyki GAAFET
19 sie, 09:58




Deep Research
Flash
Rozszerzony
Źródła
Pliki

Gemini to AI i może popełniać błędy, także co do ludzi. Twoja prywatność i Gemini
Otwiera się w nowym oknie

Analiza Architektury i Fizyki GAAFET
Spis treści
Udostępnij i wyeksportuj
Architektura i fizyka tranzystorów GAAFET w węzłach 2nm i 1.4nm: Analiza elektrostatyki, sieci BSPDN i zjawisk termicznych
Ewolucja architektura tranzystorowej: Od FinFET do GAAFET

Przejście z architektury tranzystorów płetwowych (FinFET) na konstrukcje z pełnym otoczeniem bramki (GAAFET – Gate-All-Around Field-Effect Transistor) stanowi drugą najważniejszą zmianę geometryczno-fizyczną w historii układów CMOS od czasu komercyjnego wdrożenia trójwymiarowych płetw w węźle 22 nm. Przez ponad dekadę struktury FinFET napędzały skalowanie układów scalonych zgodnie z prawem Moore'a, zastępując tranzystory planarne kanałem w postaci pionowej płetwy krzemowej otoczonej z trzech stron przez elektrodę bramki. Jednakże wraz ze skracaniem wymiarów fizycznych poniżej węzła 3 nm, architektura FinFET napotkała bariery wynikające z elektrostatyki i mechaniki kwantowej.   

Gdy szerokość płetwy w FinFET zmniejsza się poniżej 5 nm, utrzymanie precyzyjnej kontroli potencjału w dolnej części kanału przylegającej do izolacji płytkich rowów (STI – Shallow Trench Isolation) staje się fizycznie niemożliwe. Powoduje to powstawanie niepożądanych ścieżek prądu ucieczki w głębi podłoża, gwałtowny wzrost prądu w stanie wyłączenia (I
off
	​

), drastyczne nasilenie efektów krótkokanałowych (SCE – Short-Channel Effects) oraz degradację podprogowego współczynnika nachylenia (SS – Subthreshold Swing). Dodatkowo architektura FinFET boryka się z ograniczeniem w postaci kwantowania szerokości płetwy (fin quantization). W projektowaniu układów scalonych prąd przewodzenia (I
on
	​

) można zwiększać wyłącznie poprzez zwielokrotnianie dyskretnych płetw w komórce standardowej (np. tranzystor 1-fin, 2-fin), co uniemożliwia ciągłą optymalizację powierzchni, mocy i wydajności (PPA).   

Architektura GAAFET eliminuje te ograniczenia poprzez podniesienie kanału nad podłoże i całkowite owinięcie materiału bramkowego (High-k / Metal Gate) wokół krzemowych struktur przewodzących ze wszystkich czterech stron. W komercyjnych węzłach 2 nm i 1.4 nm producenci półprzewodników zdecydowali się na wariant poziomych, pionowo ułożonych nanopłatów (Nanosheets / MBCFET / RibbonFET), rezygnując z cylindrycznych drutów (Nanowires). Wybór nanopłatów wynika z ich znacznie większej efektywnej szerokości przewodzenia przy danej powierzchni rzutu tranzystora na podłoże.   

W strukturze Nanosheet całkowita efektywna szerokość kanału (W
eff
	​

) dla jednego tranzystora w komórce jest funkcją liczby nanopłatów w stosie (N
sheet
	​

), ich szerokości (W
NS
	​

) oraz grubości (T
NS
	​

):

W
eff
	​

=N
sheet
	​

⋅(2⋅W
NS
	​

+2⋅T
NS
	​

)

Przy typowej grubości nanopłata T
NS
	​

≈5 nm, dominującym składnikiem sterującym prądem przewodzenia staje się szerokość W
NS
	​

. Możliwość płynnego regulowania szerokości W
NS
	​

 za pomocą litografii w zakresie od kilkunastu do kilkudziesięciu nanometrów przyznaje projektantom swobodę ciągłego strojenia parametrów elektrycznych bez konieczności modyfikacji wysokości komórki standardowej.   

Elektrostatyka i mechanika kwantowa nanosheetu

Podstawową przewagą GAAFET jest doskonałe ograniczenie potencjału wewnątrz kanału. Nachylenie podprogowe (SS) opisuje zależność:

SS=
∂log
10
	​

I
d
	​

∂V
gs
	​

	​

=ln(10)⋅
q
k
B
	​

T
	​

⋅(1+
C
ox
	​

C
d
	​

	​

)

gdzie C
d
	​

 oznacza pojemność obszaru zubożonego, a C
ox
	​

 jest pojemnością tlenku bramkowego. Dzięki otoczeniu nanopłata bramką ze wszystkich czterech stron, pojemność C
ox
	​

 dominuje nad pojemnością podłoża, co pozwala zbliżyć wartość SS do teoretycznej granicy termojonowej wynoszącej ∼60 mV/dec w temperaturze pokojowej. Równocześnie zjawisko obniżenia bariery indukowane drenem (DIBL – Drain-Induced Barrier Lowering) zostaje zredukowane do wartości poniżej 30 mV/V, wygaszając efekty krótkokanałowe przy fizycznych długościach bramki L
g
	​

≈12–15 nm.   

Skalowanie grubości nanopłata do wartości T
NS
	​

≤5 nm wprowadza jednak silne efekty uwięzienia kwantowego w kierunku pionowym. Powstająca wąska studnia potencjału powoduje rozszczepienie pasm przewodnictwa na dyskretne podpasma kwantowe. Skutkuje to zmianą masy efektywnej nośników oraz wzmożonym rozpraszaniem na chropowatości powierzchni (surface roughness scattering) na granicach fazowych krzemu z tlenkiem. Efekt ten degraduje ruchliwość elektronów i dziur, co wymaga stosowania inżynierii naprężeń mechanicznych (strain engineering) – między innymi poprzez epitaksjalny wzrost stóp SiGe w obszarach źródła i drenu dla tranzystorów pMOS.   

Istotnym elementem strukturalnym GAAFET są przekładki wewnętrzne (Inner Spacers). Formowane w selektywnym procesie trawienia wnękowego warstw SiGe w wielowarstwowym stosie Si/SiGe, przekładki wewnętrzne oddzielają od siebie elementy metalowej bramki wrażliwe na spadek potencjału od epitaksjalnych obszarów źródła i drenu. Ich precyzyjne wykonanie zapobiega powstawaniu zwarć oraz drastycznie obniża pasożytnicze pojemności nakładania (C
gs
	​

,C
gd
	​

), które w przeciwnym razie zniwelowałyby zyski wynikające z wyższego prądu przewodzenia.   

Cecha elektrostatyczna i konstrukcyjna	FinFET (Węzeł 3 nm)	GAAFET Nanosheet (Węzeł 2 nm / 1.4 nm)
Geometria kanału	

Pionowa płetwa krzemowa

	

Poziome, nakładające się nanopłaty


Pokrycie bramką	

3 strony (Tri-gate)

	

4 strony (Gate-All-Around)


Kwantowanie szerokości	

Dyskretne (Liczba płetw: 1, 2, 3)

	

Ciągłe (Regulowana szerokość W
NS
	​

)


Nachylenie podprogowe (SS)	

70–75 mV/dec

[cite: 3, 8]

	

60–65 mV/dec

[cite: 3, 8]


DIBL (Drain-Induced Barrier Lowering)	

45–60 mV/V

[cite: 8]

	

<30 mV/V

[cite: 8]


Izolacja pasożytnicza S/D	

Zależna od właściwości STI

	

Zdefiniowana przez przekładki Inner Spacers


Skalowanie napięcia V
min
	​

	

Ograniczone przez wariancję dopasowania

	

Wysokie (Lepsza spójność V
th
	​

)

  
Analiza porównawcza węzłów 2nm i 1.4nm czołowych producentów

Wirtualny wyścig technologiczny w erze Ångströma koncentruje się wokół rozwiązań trzech głównych dostawców półprzewodników: TSMC, Intel Foundry oraz Samsung Foundry. Każde z przedsiębiorstw obrało odmienną strategię w zakresie sekwencji wprowadzania tranzystorów GAA oraz sieci zasilania od spodu (BSPDN).   

TSMC: N2, N2P oraz A16

TSMC zastosowało strategię etapowego wprowadzania innowacji w celu minimalizacji ryzyka wytwórczego. Węzeł podstawowy TSMC N2 (klasa 2 nm) wdraża pierwszą generację tranzystorów Nanosheet GAA z zachowaniem tradycyjnego zasilania od strony przedniej (Frontside PDN). Zasilanie to wspierane jest przez zintegrowane pojemności odsprzęgające o wysokiej gęstości. Produkcja masowa węzła N2 rozpoczęła się w czwartym kwartale 2025 roku.   

Rozwinięciem architektury N2 jest technologia NanoFlex, która umożliwia projektantom swobodne łączenie w obrębie tego samego bloku logicznego komórek standardowych o różnej wysokości i zróżnicowanej szerokości nanopłatów. Warianty niskie (Short Cells) optymalizują gęstość i zmniejszają pobór mocy, podczas gdy warianty wysokie (Tall Cells) maksymalizują prąd przewodzenia dla ścieżek krytycznych w układach HPC.   

Głównym krokiem technologicznym TSMC w obszarze zasilania od spodu jest węzeł A16 (klasa 1.6 nm), którego produkcja masowa została zaplanowana na drugą połowę 2026 roku. A16 łączy ulepszone tranzystory Nanosheet z nowatorską siecią Super Power Rail (SPR). Architektura SPR wyróżnia się bezpośrednim podłączeniem tylnej sieci zasilającej do epitaksjalnych obszarów źródła i drenu tranzystorów, co eliminuje konieczność przeznaczania miejsca na wewnętrzne przelotki w obrębie komórki. W porównaniu do węzła N2P, architektura A16 zapewnia:   

Wzrost wydajności o 8–10% przy stałym napięciu zasilania.   

Redukcję poboru mocy o 15–20% przy zachowaniu tej samej częstotliwości.   

Wzrost gęstości upakowania logiki o 1.10× (oraz do 1.12× w gęstych strukturach połączeń).   

Intel Foundry: Intel 18A oraz Intel 14A

Intel obrał bardziej agresywny schemat wdrożeniowy, wprowadzając równocześnie w jednym węźle nową geometrię tranzystorów RibbonFET (własna nazwa tranzystorów GAA Nanosheet) oraz sieć zasilania od spodu PowerVia. Węzeł Intel 18A (klasa 1.8 nm) wszedł w fazę masowej produkcji na przełomie lat 2025/2026 w procesorach z rodziny Panther Lake.   

Węzeł 18A charakteryzuje się podziałką bramki (CPP – Contacted Poly Pitch) rzędu 50 nm oraz podziałką najgęstszych warstw metalizacji (Metal Pitch) równą 32 nm. Połączenie tranzystorów RibbonFET z siecią PowerVia pozwoliło na wyeliminowanie spadków napięcia oraz odblokowanie gęstości upakowania warstw sygnałowych.   

Następcą technologicznym jest węzeł Intel 14A (klasa 1.4 nm), będący pierwszym w branży procesem zaprojektowanym pod kątem pełnego wykorzystania litografii EUV o wysokiej aperturze numerycznej (High-NA EUV, 0.55 NA). Proces 14A wprowadza drugą generację tranzystorów RibbonFET 2, usprawnioną sieć PowerDirect oraz tak zwane Turbo Cells. Turbo Cells to makra komórek pozwalające na wybiórcze dostrajanie stosunku wydajności do mocy na poziomie poszczególnych bloków logicznych. W stosunku do węzła 18A, technologia 14A oferuje:   

Wzrost wydajności o 15–20% przy stałym poborze mocy.   

Obniżenie zużycia energii o 25–35% przy tej samej częstotliwości.   

Zwiększenie gęstości logiki o maksymalnie 30%.   

Samsung Foundry: SF2 oraz SF1.4

Samsung jako pierwszy producent skomercjalizował architekturę GAA pod nazwą MBCFET (Multi-Bridge-Channel FET) w węźle 3 nm (SF3). Druga generacja tej architektury stanowi podstawę procesu SF2 (klasa 2 nm), wdrożonego do produkcji w 2025 roku w procesorach mobilnych Exynos 2600.   

Węzeł SF2 oferuje gęstość tranzystorów na poziomie 231 MTr/mm
2
, podziałkę CPP ∼48 nm oraz podziałkę metalizacji 28 nm. Podobnie jak w przypadku TSMC N2, pierwsza wersja SF2 wykorzystuje zasilanie od strony przedniej. Wariant z siecią zasilania od spodu (SF2Z) zaplanowano na rok 2027.   

Kluczową innowacją Samsunga w klasie sub-2nm ma być proces SF1.4 (1.4 nm), z planowanym terminem wdrażania w 2027 roku. Zmianą architektoniczną w SF1.4 jest zwiększenie liczby nanopłatów w pojedynczym stosie tranzystora z 3 do 4. Zwiększenie pionowego stosu o czwarty nanopłat umożliwia bezpośrednie zwiększenie efektywnej szerokości tranzystora (W
eff
	​

) o 33% bez zwiększania powierzchni komórki standardowej. Przekłada się to na wzrost prądu I
on
	​

, poprawę stabilności komórek pamięci SRAM V
min
	​

 oraz wyższą sprawność energetyczną całego układu.   

Parameter / Specyfikacja	

TSMC N2

	

TSMC A16

	

Intel 18A

	

Intel 14A

	

Samsung SF2

	

Samsung SF1.4


Typ tranzystora	

Nanosheet GAA

	

Nanosheet GAA Gen 2

	

RibbonFET GAA

	

RibbonFET 2

	

MBCFET GAA Gen 2

	

MBCFET (Stos 4-płatowy)


Contacted Poly Pitch (CPP)	

∼48 nm

[cite: 9, 28]

	

∼45–48 nm

[cite: 9]

	

50 nm

[cite: 5, 9]

	

<45 nm

[cite: 9]

	

∼48–50 nm

[cite: 9, 27]

	

<40 nm

[cite: 9]


Minimum Metal Pitch (MMP)	

26 nm

[cite: 9]

	

<24 nm

[cite: 9]

	

32 nm

[cite: 9]

	

<20 nm

[cite: 9]

	

28 nm

[cite: 9]

	

<20 nm

[cite: 9]


Gęstość logiki (MTr/mm²)	

∼313

[cite: 9]

	

∼340–350

[cite: 9, 15, 18]

	

∼238

[cite: 9]

	

>300

[cite: 22]

	

∼231

[cite: 9, 11]

	

>320

[cite: 11, 25]


Rozmiar komórki SRAM (µm²)	

0.0175

[cite: 9]

	

<0.0165

[cite: 18]

	

0.0210

[cite: 9]

	Brak danych	Brak danych	Brak danych
Architektura zasilania	

Frontside PDN

	

Super Power Rail (BSPDN)

	

PowerVia (BSPDN)

	

PowerDirect (BSPDN)

	

Frontside PDN

	

BSPDN


Litografia EUV	

Standard (0.33 NA)

	

Standard (0.33 NA)

	

Standard (0.33 NA)

	

High-NA (0.55 NA)

	

Standard (0.33 NA)

	

High-NA (0.55 NA)


Status wdrożenia	

Produkcja Q4 2025

	

Produkcja H2 2026

	

Produkcja Q4 2025

	

Wdrożenie ~2027/28

	

Produkcja 2025

	

Wdrożenie 2027

  
Architektura sieci zasilania od spodu (Backside Power Delivery Network - BSPDN)

W tradycyjnym modelu zasilania układowego (Frontside PDN) zarówno połączenia sygnałowe, jak i magistrale dystrybucji mocy (V
dd
	​

 i V
ss
	​

) konkurują o te same najniższe warstwy metalizacji (M0, M1, M2) położone bezpośrednio nad tranzystorami. Ze względu na skalowanie podziałki przewodów poniżej 30 nm, rezystancja miedzianych ścieżek zasilających rośnie gwałtownie na skutek rozpraszania elektronów na granicach ziaren i cienkich barierach dyfuzyjnych. W konsekwencji gęste układy scalone cierpią na znaczne spadki napięcia zasilania (IR Drop), szum komutacyjny oraz kongestię trasowania sygnałów, co wymusza stosowanie kompromisowych wydłużeń ścieżek połączeniowych.   

Technologia BSPDN rozwiązuje ten problem poprzez rozdzielenie płaszczyzny zasilania od płaszczyzny sygnałowej. Warstwy metalizacji po stronie przedniej (Frontside) zostają w całości dedykowane dla połączeń sygnałowych o niskiej pojemności, natomiast magistrale zasilające o dużej szerokości i przewodności zostają przeniesione na tylną stronę wafla krzemowego (Backside).   

Integracja procesowa: Etapy fabrykacji BSPDN

Wdrożenie sieci BSPDN wymaga skomplikowanych operacji technologicznych w fazie wykończeniowej wafla (Back-End-of-Line / Wafer Reconstitution):   

Sformowanie struktur przednich (FEOL i BEOL): Następuje klasyczna produkcja tranzystorów GAAFET oraz wytworzenie pełnego stosu połączeń sygnałowych na przedniej stronie wafla.   

Spajanie z waflem nośnym (Carrier Wafer Bonding): Przednia strona wafla zostaje odwrócona i połączona za pomocą bezpośredniego spajania tlenkowego (direct oxide bonding) z krzemowym waflem przenoszącym o grubości około 600–700 μm, który zapewnia sztywność mechaniczną podczas dalszych etapów.   

Ekstremalne odchudzanie podłoża (Extreme Wafer Thinning): Pierwotne podłoże krzemowe jest poddawane szlifowaniu mechanicznemu oraz chemiczno-mechanicznej polaryzacji (CMP) od strony tylnej. Podłoże zostaje zredukowane z grubości kilkuset mikrometrów do zaledwie kilkudziesięciu nanometrów, odsłaniając spód stref aktywnych tranzystorów.   

Litografia tylna i metalizacja BSPDN: W odsłoniętym spodzie formowane są przelotki zasilające oraz grube, niskooporowe szyny zasilające z miedzi lub rutenu (Cu / Ru).   

Intel PowerVia vs. TSMC Super Power Rail (SPR)

Mimo zbieżnego celu końcowego, architektury połączeń na poziomie komórki w rozwiązaniach marek Intel i TSMC różnią się pod względem koncepcyjnym:

Intel PowerVia (Nano-TSV): Intel wykorzystuje mikroskopijne przelotki przechodzące przez krzem (nano-TSVs). Są one formowane na etapie FEOL jako tak zwane ślepe przelotki (blind vias) wewnątrz obszaru komórki standardowej. Podczas odsłaniania tylnej strony wafla, przelotki nano-TSV zostają otwarte i połączone z szynami zasilającymi. Konstrukcja ta obniża skomplikowanie bezpośredniego kontaktu z kanałem, jednak zużywa niewielki fragment powierzchni wewnątrz układu strefy aktywnej komórki.   

TSMC Super Power Rail (SPR): TSMC stosuje bardziej bezpośredni schemat połączeń. Super Power Rail łączy tylną sieć zasilającą bezpośrednio z epitaksjalnymi obszarami źródła i drenu (S/D) tranzystorów od ich spodu. Eliminuje to konieczność stosowania przelotek nano-TSV wewnątrz strefy logicznej komórki, pozostawiając całą przestrzeń przednią dla bramek i połączeń sygnałowych. Choć rozwiązanie to wymaga precyzyjnego trawienia selektywnego i kontroli naprężeń, zapewnia najwyższą gęstość upakowania i najniższą rezystancję styku.   

Korzyści PPA wynikające z wdrożenia sieci zasilania od spodu obejmują redukcję spadu napięcia (IR Drop) o 30–40%, co przekłada się na mniejsze wahania napięcia i wyższą częstotliwość pracy przy tym samym poziomie zasilania. Odciążenie warstw przednich umożliwia również zwiększenie stopnia wykorzystania powierzchni komórki (Cell Utilization) o 10–15% oraz redukcję liczby skomplikowanych masek fotolitograficznych po stronie przedniej.   

Fizyka zjawisk termicznych i samonagrzewanie (Self-Heating Effect - SHE)

Wdrożenie tranzystorów GAAFET w połączeniu z siecią BSPDN stwarza istotne wyzwania w dziedzinie inżynierii cieplnej. Tranzystory w węzłach 2 nm i 1.4 nm charakteryzują się wysoką gęstością mocy strat generowanej w bardzo małych objętościach, co nasila zjawisko samonagrzewania (SHE – Self-Heating Effect).   

Mechanizmy degradacji przewodności cieplnej w nanosheetach

W krzemie objętościowym (Bulk Si) przewodność cieplna w temperaturze pokojowej wynosi κ
bulk
	​

≈148 W/(m⋅K). Głównym nośnikiem ciepła w krzemie są fonony akustyczne, których średnia droga swobodna (Λ
ph
	​

) wynosi od kilkudziesięciu do kilkuset nanometrów.

Gdy wymiar krzemu zostaje zredukowany do grubości nanopłata T
NS
	​

≈5 nm, zachodzą dwa kluczowe zjawiska termodynamiczne:   

Uwięzienie fononów (Phonon Confinement): Modyfikacja widma dyspersji fononowej w nanostrukturze powoduje spadek prędkości grupowej fononów (v
g
	​

), co bezpośrednio obniża zdolność do przewodzenia ciepła.

Rozpraszanie na granicach powierzchni (Boundary Scattering): Fonony transportujące energię cieplną ulegają nieustannemu rozpraszaniu na górnej i dolnej powierzchni nanopłata. Długość drogi swobodnej fononów zostaje ograniczona przez grubość T
NS
	​

.

W konsekwencji efektywna przewodność cieplna nanopłata krzemowego (κ
eff
	​

) spada o rządy wielkości, osiągając wartości w zakrasie:

κ
eff
	​

≈15–25 W/(m⋅K)

Oznacza to, że sam kanał krzemowy staje się słabym przewodnikiem ciepła.   

Dodatkowo w strukturze GAAFET każdy nanopłat jest otoczony materiałami dielektrycznymi o bardzo niskiej przewodności cieplnej:

Dielektryk bramkowy High-k (HfO
2
	​

): κ
HfO
2
	​

	​

≈1.5–2.5 W/(m⋅K).   

Przekładki wewnętrzne (Inner Spacers – SiN,SiOCN): κ
spacer
	​

≈1.2–2.0 W/(m⋅K).   

Dielektryk dołka i izolacja dolna (BDI – Bottom Dielectric Isolation): κ
SiO
2
	​

	​

≈1.4 W/(m⋅K).   

W efekcie ciepło generowane na skutek rozpraszania nośników prądu (joule heating) wewnątrz nanopłatów zostaje zamknięte w pułapce termicznej, a jego odpływ drogą przewodzenia przez podłoże lub elektrodę bramki zostaje utrudniony.   

Wpływ BSPDN na dysypację ciepła i niezawodność tranzystora

Usunięcie grubego podłoża krzemowego podczas tworzenia sieci BSPDN pozbawia układ tradycyjnego, objętościowego bufora cieplnego. Strefa aktywna tranzystorów znajduje się blisko zewnętrznych powierzchni wafla, co powoduje ponad dwukrotny wzrost gęstości strumienia ciepła generowanego na tylnej stronie w porównaniu do technologii z tradycyjnym zasilaniem przednim. Z drugiej strony, grube miedziane szyny zasilające z tyłu wafla mogą pełnić funkcję odprowadzalników ciepła, pod warunkiem zastosowania bezpośredniego chłodzenia obudowy od strony podłoża.   

Niewystarczające odprowadzanie ciepła i wzrost lokalnej temperatury złącza (T
j
	​

) przyspieszają główne mechanizmy degradacyjne w tranzystorach GAAFET:   

Niestabilność napięcia pod wpływem temp. i polaryzacji (BTI): Zjawiska NBTI (dla pMOS) oraz PBTI (dla nMOS) wykazują zależność od temperatury. Podwyższone T
j
	​

 generuje pułapki na granicy fazowej tlenku i krzemu, wywołując dryf napięcia progowego (V
th
	​

) i spadek szybkości przełączania tranzystorów.   

Iniekcja gorących nośników (HCI): Rozpraszanie wysokoenergetycznych nośników ulega nasileniu w obecności silnych pól elektrycznych przy krawędziach drenu i podwyższonej temperaturze, trwale degradując prąd włączenia I
on
	​

.   

Czasowe przebicie dielektryka (TDDB): Przebicie cienkich warstw dielektryka bramkowego oraz dielektryków międzywarstwowych MOL (Middle-of-Line) przyspiesza w podwyższonej temperaturze, skracając czas bezawaryjnej pracy układu.   

Wnioski i perspektywy rozwoju

Wdrożenie architektury GAAFET (Nanosheet, MBCFET, RibbonFET) w węzłach 2 nm i 1.4 nm stanowi konieczny etap rozwoju fizyki tranzystorowej, pozwalający na dalsze skalowanie gęstości i wydajności układów scalonych. Pełna, czterostronna kontrola elektrostatyczna nad kanałem usuwa bariery technologiczne tranzystorów FinFET, ograniczając prądy ucieczki oraz umożliwiając obniżenie napięcia zasilania V
min
	​

.   

Równoległa integracja sieci zasilania od spodu (BSPDN – PowerVia, Super Power Rail) usuwa ograniczenia transportu mocy i redukuje kongestię w warstwach metalizacji sygnałowej. Rozwiązania takie jak TSMC Super Power Rail, bazujące na bezpośrednim kontakcie ze strefami źródła i drenu, wyznaczają kierunki maksymalizacji gęstości logiki w klasie sub-2nm.   

Głównym wyzwaniem pozostaje inżynieria cieplna. Samonagrzewanie (SHE) w ultra-cienkich nanopłatach (T
NS
	​

≈5 nm) wymusza stosowanie zaawansowanych technik optymalizacji współzależnej (DTCO) na etapie projektowania układów.   

Dalszy rozwój architektury tranzystorowej w obszarze poniżej węzła 1.4 nm wyznaczają następujące technologie:

Tranzystory komplementarne CFET (Complementary FET): Pionowe układanie tranzystora nFET bezpośrednio nad tranzystorem pFET, co pozwoli na dalszą redukcję powierzchni komórki standardowej o kolejne 30–50%.   

Materiały dwuwymiarowe (2D TMD): Zastąpienie krzemowego nanopłata monowarstwami z dwuwymiarowych półprzewodników z grupy dichalkogenków metali przejściowych (np. MoS
2
	​

,WS
2
	​

), zapewniających wysoką ruchliwość nośników przy grubości kanału poniżej 1 nanometra.   

Powszechne wykorzystanie High-NA EUV: Wykorzystanie urządzeń litograficznych o aperturze numerycznej 0.55 NA w celu eliminacji skomplikowanych masek wielokrotnego naświetlania.   

Źródła wykorzystane w tym raporcie
pmc.ncbi.nlm.nih.gov
A Review of Reliability in Gate-All-Around Nanosheet Devices - PMC
Otwiera się w nowym oknie
resources.system-analysis.cadence.com
Comparing FinFETs vs. GAAFETs | System Analysis Blog | Cadence
Otwiera się w nowym oknie
scribd.com
FinFET vs GAAFET: Transistor Evolution | PDF - Scribd
Otwiera się w nowym oknie
ecrionix.org
FinFET vs GAA — How the Modern Transistor Evolved - EcrioniX
Otwiera się w nowym oknie
insidedeeptech.com
GAAFET and Nanosheet Transistors: A Full Guide (2026) - Inside Deep Tech
Otwiera się w nowym oknie
mdpi.com
A Review of the Gate-All-Around Nanosheet FET Process Opportunities - MDPI
Otwiera się w nowym oknie
semiengineering.com
Moving To GAA FETs - Semiconductor Engineering
Otwiera się w nowym oknie
researchgate.net
(PDF) Gate-All-Around FETs: Nanowire and Nanosheet Structure - ResearchGate
Otwiera się w nowym oknie
en.wikipedia.org
2 nm process - Wikipedia
Otwiera się w nowym oknie
arxiv.org
[2204.01423] Phonon heat capacity and self-heating normal domains in NbTiN nanostrips
Otwiera się w nowym oknie
cyberraiden.wordpress.com
2nm Semiconductor Fabrication: Technical Hurdles in TSMC N2, Samsung SF2, and Intel 18A - Cyber Raiden
Otwiera się w nowym oknie
aminext.blog
Chip Giants' Showdown: TSMC, Samsung, Intel Tech Deep Dive - AmiNext
Otwiera się w nowym oknie
aminext.blog
What is Backside Power (BSPDN)? The Intel vs TSMC 2nm War - AmiNext
Otwiera się w nowym oknie
tsmc.com
A16 Technology - Taiwan Semiconductor Manufacturing Company Limited
Otwiera się w nowym oknie
semiwiki.com
TSMC A16 Process Technology Wiki - SemiWiki
Otwiera się w nowym oknie
semiengineering.com
TSMC Uncorks A16 With Super Power Rail - Semiconductor Engineering
Otwiera się w nowym oknie
vlsi26.mapyourshow.com
A16 Angstrom-class CMOS Technology featuring Enhanced Nanosheet Transistors with Super-Power Rail (backside direct contact power delivery) for AI and HPC Applications (Late News)
Otwiera się w nowym oknie
wccftech.com
TSMC's A16 '1.6nm' Node Promises 10% Speed Boost or 20% Power Cut Over 2nm, With Backside Power Hitting Production by Q4 2026 - Wccftech
Otwiera się w nowym oknie
fiisual.com
What Is Backside Power Delivery Network (BSPDN)? The Technological Differences Among TSMC, Samsung, and Intel | fiisual Blog
Otwiera się w nowym oknie
remio.ai
Inside Intel's 18A Node: RibbonFET, PowerVia, and the Architecture Behind Panther Lake
Otwiera się w nowym oknie
dailymozaic.com
TSMC A16 vs Intel 18A: The Angstrom Node Revolution in 2026 - DailyMozaic
Otwiera się w nowym oknie
intel.com
Semiconductor Manufacturing Process | Intel 14A, 18A, and 3
Otwiera się w nowym oknie
fool.com
The Chip Technology That Finally Gives Intel an Edge Over TSMC | The Motley Fool
Otwiera się w nowym oknie
avecas.in
The Vertical Revolution: Why Backside Power Delivery is the Defining Shift for 2nm Silicon
Otwiera się w nowym oknie
trendforce.com
[News] Battle of the Titans in the Angstrom Era – TSMC's A16 Competes with Intel's 14A and Samsung's SF1.4 - TrendForce
Otwiera się w nowym oknie
anysilicon.com
Intel Begins Work on 10A and 7A Process Nodes as 14A Roadmap Moves Toward Key PDK Release - AnySilicon
Otwiera się w nowym oknie
semiwiki.com
Samsung 2nm Process Technology Wiki - SemiWiki
Otwiera się w nowym oknie
reddit.com
18A and N2P specifications leaked : r/hardware - Reddit
Otwiera się w nowym oknie
aminext.blog
TSMC A16 Process Technology Explained: Ushering in the Angstrom Era - AmiNext
Otwiera się w nowym oknie
reddit.com
Semiconductor Engineering: "Backside Power Delivery Adds New Thermal Concerns" : r/hardware - Reddit
Otwiera się w nowym oknie
scribd.com
20240911101100 AI賦能，半導體晶片技術與產業變革| PDF - Scribd
Otwiera się w nowym oknie
Źródła przeczytane, ale niewykorzystane w raporcie
webthesis.biblio.polito.it
Nanosheet-GAAFETs modeling and circuit performance evaluation - WebThesis
Otwiera się w nowym oknie
tsmc.com
HPC Platform – Advanced Technologies - Taiwan Semiconductor Manufacturing Company Limited
Otwiera się w nowym oknie
scribd.com
Intel 18A Platform Technology Featuring RibbonFET GAA and PowerVia For Advanced High-Performance Computing | PDF | Electronic Circuits - Scribd
Otwiera się w nowym oknie
youtube.com
Intel PowerVia vs TSMC Super Power Rail — The Battle to Power the AI Chip - YouTube
Otwiera się w nowym oknie
semiwiki.com
Intel vs TSMC in Risk Taking | SemiWiki
Otwiera się w nowym oknie
reddit.com
TSMC unveils 1.6nm process technology with backside power delivery, rivals Intel's competing design - Reddit
Otwiera się w nowym oknie
medium.com
Demystifying VLSI Technology Nodes: From Basics to the Cutting Edge (2026 Update) | by Dhruvesh Kamble | Medium
Otwiera się w nowym oknie
Pomysły
Cel i zakres analizy
Rozpoczynam szczegółową analizę fizyki oraz architektury tranzystorów wielobramkowych GAAFET (Nanosheet / MBCFET) dla kluczowych węzłów technologicznych 2nm i 1.4nm. W centrum uwagi znajdują się elektrostatyka kanału, zjawiska samonagrzewania (SHE), nowatorskie sieci zasilania od spodu (BSPDN / PowerVia / Super PowerRail) oraz bezpośrednie porównanie planów technologicznych TSMC, Intela i Samsunga.
Fizyka nanosheet i zasilanie BSPDN
Przystępuję do weryfikacji danych na temat geometrii nanosheetów, w tym redukcji pojemności pasożytniczych przez przekładki wewnętrzne (inner spacers) oraz mechanizmów pułapkowania ciepła z powodu ograniczenia fononowego i izolacji dielektrycznej. Równolegle badam wpływ technologii zasilania tylnego na redukcję spadków napięcia IR drop oraz potencjał grubych miedzianych szyn zasilających do odprowadzania ciepła z tranzystorów.
Planowane działania wyszukiwawcze
Planuję przeszukać publikacje konferencyjne IEEE IEDM, VLSI Symposium oraz opracowania branżowe, aby pozyskać precyzyjne parametry struktur RibbonFET, MBCFET i Nanosheet dla procesów TSMC N2/A16, Intel 18A/14A oraz Samsung SF2/SF1.4.
insidedeeptech.com
GAAFET and Nanosheet Transistors: A Full Guide (2026) - Inside Deep Tech
resources.system-analysis.cadence.com
Comparing FinFETs vs. GAAFETs | System Analysis Blog | Cadence
scribd.com
FinFET vs GAAFET: Transistor Evolution | PDF - Scribd
mdpi.com
A Review of the Gate-All-Around Nanosheet FET Process Opportunities - MDPI
pmc.ncbi.nlm.nih.gov
A Review of Reliability in Gate-All-Around Nanosheet Devices - PMC
ecrionix.org
FinFET vs GAA — How the Modern Transistor Evolved - EcrioniX
semiengineering.com
Moving To GAA FETs - Semiconductor Engineering
webthesis.biblio.polito.it
Nanosheet-GAAFETs modeling and circuit performance evaluation - WebThesis
researchgate.net
(PDF) Gate-All-Around FETs: Nanowire and Nanosheet Structure - ResearchGate
vlsi26.mapyourshow.com
A16 Angstrom-class CMOS Technology featuring Enhanced Nanosheet Transistors with Super-Power Rail (backside direct contact power delivery) for AI and HPC Applications (Late News)
Przewaga elektrostatyczna i elastyczność GAAFET
Analizuję fizykę i geometrię tranzystorów GAAFET, które dzięki pełnemu otoczeniu kanału bramką z czterech stron zapewniają znacząco lepszą kontrolę elektrostatyczną i redukcję prądów upływu w porównaniu do technologii FinFET. Przeglądam również rolę wewnętrznych przekładek izolacyjnych (inner spacers) oraz dolnej izolacji dielektrycznej (BDI) w ograniczaniu pojemności pasożytniczych i prądów ucieczki do podłoża. Istotną zaletą nanosheetów jest możliwość płynnego dostosowywania szerokości kanału, co eliminuje ograniczenia dyskretnego skalowania znane z FinFET.
Rozwój węzłów sub-2nm i technologii zasilania
Zestawiam plany czołowych producentów półprzewodników dla węzłów 2nm i 1.4nm. Badam architekturę TSMC (N2, N2P oraz A16 z technologią Super PowerRail), rozwiązania Intela (18A i 14A oparte na RibbonFET i PowerVia) oraz strategię Samsunga z technologią MBCFET w procesach SF2 i SF1.4. Analizuję, jak przeniesienie sieci zasilania na tylną stronę wafka (BSPDN) pozwala na zmniejszenie spadków napięcia IR drop, odciążenie przednich warstw połączeń sygnałowych oraz dalszą redukcję wysokości komórek standardowych.
Wyzwania termiczne i dalszy plan badawczy
Zgłębiam zjawisko samonagrzewania (SHE), w którym uwięzienie ciepła w cienkich nanosheetach Si z powodu ograniczeń przestrzennych fononów i izolacji tlenkowej prowadzi do degradacji ruchliwości nośników, obniżenia niezawodności i przyspieszenia elektromigracji. Badam, w jakim stopniu miedziana sieć zasilająca BSPDN może służyć jako radiator wspomagający odprowadzanie ciepła. Zamierzam przeprowadzić szczegółowe wyszukiwania w celu pozyskania dokładnych parametrów geometrycznych węzłów oraz wyników badań dotyczących zarządzania termicznego.
tsmc.com
A16 Technology - Taiwan Semiconductor Manufacturing Company Limited
tsmc.com
HPC Platform – Advanced Technologies - Taiwan Semiconductor Manufacturing Company Limited
en.wikipedia.org
2 nm process - Wikipedia
reddit.com
18A and N2P specifications leaked : r/hardware - Reddit
aminext.blog
TSMC A16 Process Technology Explained: Ushering in the Angstrom Era - AmiNext
wccftech.com
TSMC's A16 '1.6nm' Node Promises 10% Speed Boost or 20% Power Cut Over 2nm, With Backside Power Hitting Production by Q4 2026 - Wccftech
semiengineering.com
TSMC Uncorks A16 With Super Power Rail - Semiconductor Engineering
semiwiki.com
TSMC A16 Process Technology Wiki - SemiWiki
remio.ai
Inside Intel's 18A Node: RibbonFET, PowerVia, and the Architecture Behind Panther Lake
scribd.com
Intel 18A Platform Technology Featuring RibbonFET GAA and PowerVia For Advanced High-Performance Computing | PDF | Electronic Circuits - Scribd
reddit.com
Semiconductor Engineering: "Backside Power Delivery Adds New Thermal Concerns" : r/hardware - Reddit
Analiza węzłów sub-2nm i technologii zasilania
Analizuję specyfikacje procesów TSMC (N2, A16 z Super PowerRail), Intela (18A, 14A z RibbonFET i PowerVia) oraz Samsunga (SF2, SF1.4 z MBCFET). Zaobserwowałem istotne różnice w harmonogramach wdrażania zasilania od spodu – Intel wprowadza PowerVia w węźle 18A, podczas gdy TSMC planuje integrację Super PowerRail dopiero w A16, omijając ten element w bazowym N2.
Zjawiska termiczne w nanosheetach z BSPDN
Rozwiązuję kwestię wpływu zasilania od spodu na zjawisko samonagrzewania (SHE). Z jednej strony grube miedziane szyny na odwrocie struktury mogą działać jak dodatkowy radiator odprowadzający ciepło z kanałów nanosheet, z drugiej strony cieńszy krzem po szlifowaniu i dodatkowe warstwy izolacyjne modyfikują opór termiczny (Rth), co wymaga dokładniejszego przeanalizowania bilansu cieplnego.
Kolejne kroki badawcze
Planuję wykonać precyzyjne wyszukiwania w celu porównania konkretnych rozwiązań architektonicznych styków (od bezpośrednich połączeń z źródłem/drenem po ukryte szyny zasilające) oraz zebrania dokładnych parametrów geometrycznych (CPP, metal pitch, wymiary nanosheetów) dla procesów sub-2nm.
aminext.blog
What is Backside Power (BSPDN)? The Intel vs TSMC 2nm War - AmiNext
youtube.com
Intel PowerVia vs TSMC Super Power Rail — The Battle to Power the AI Chip - YouTube
dailymozaic.com
TSMC A16 vs Intel 18A: The Angstrom Node Revolution in 2026 - DailyMozaic
semiwiki.com
Intel vs TSMC in Risk Taking | SemiWiki
fiisual.com
What Is Backside Power Delivery Network (BSPDN)? The Technological Differences Among TSMC, Samsung, and Intel | fiisual Blog
avecas.in
The Vertical Revolution: Why Backside Power Delivery is the Defining Shift for 2nm Silicon
fool.com
The Chip Technology That Finally Gives Intel an Edge Over TSMC | The Motley Fool
reddit.com
TSMC unveils 1.6nm process technology with backside power delivery, rivals Intel's competing design - Reddit
Różnice w architekturze BSPDN
Syntetyzuję zebrane dane dotyczące odmiennych podejść do zasilania od spodu. Przeglądam specyfikę technologii Intel PowerVia, która wykorzystuje wstępnie osadzone nano-TSV tworzone podczas procesów front-end jako ukryte połączenia pionowe, w porównaniu do podejścia TSMC Super PowerRail w węźle A16. Rozwiązanie TSMC eliminuje klasyczne struktury TSV na rzecz bezpośredniego stykania tylnych szyn miedzianych ze źródłem i drenem tranzystora, co znacząco obniża rezystancję kontaktową i redukuje spadki napięcia IR drop o ponad 30%.
Harmonogramy i przewagi rynkowe
Analizuję różnice w strategii komercjalizacji pomiędzy liderami rynku. Dostrzegam, że Intel uzyskuje przewagę czasową, wprowadzając zasilanie tylne PowerVia wraz z tranzystorami RibbonFET już w procesie 18A (m.in. w układach Panther Lake), podczas gdy TSMC planuje wdrożenie Super PowerRail w węźle A16 w późniejszym terminie, skupiając się wcześniej na stabilizacji samej architektury N nanosheet w węzłach N2 i N2P.
Szczegółowa analiza publikacji naukowych
Przechodzę do pogłębionej analizy materiałów źródłowych dotyczących niezawodności struktur nanosheet oraz fizyki samonagrzewania (SHE). Zamierzam zapoznać się ze szczegółowymi publikacjami naukowymi, aby dokładnie zbadać geometrie kanałów, opór termiczny oraz wpływ podwyższonej temperatury na degradację tranzystorów (BTI, TDDB) i mechanizmy odprowadzania ciepła przez struktury BSPDN.
pmc.ncbi.nlm.nih.gov
A Review of Reliability in Gate-All-Around Nanosheet Devices - PMC
insidedeeptech.com
GAAFET and Nanosheet Transistors: A Full Guide (2026)
Szczegóły geometryczne i architektoniczne węzłów
Syntetyzuję szczegółowe parametry geometryczne dla procesów sub-2nm. Zaobserwowałem, że Intel w węźle 18A deklaruje podziałkę styków bramkowych (CPP) na poziomie 50 nm oraz wysokości komórek 180 nm i 160 nm, podczas gdy TSMC stawia na elastyczną regulację szerokości nanosheetów (od 15 nm do 40 nm) w ramach koncepcji NanoFlex, co pozwala dostosowywać wydajność prądową bez zmiany powierzchni komórki.
Rozbieżności w harmonogramach i nazewnictwie
Rozstrzygam kwestię różnic w implementacji zasilania od spodu pomiędzy producentami. Podczas gdy Intel wdroży PowerVia już w 18A, TSMC zarezerwowało Super PowerRail dopiero dla architektury A16, oferując w N2 tradycyjne zasilanie od góry. Samsung planuje wdrożenie rozwiązania BSPDN w wariancie SF2Z, przesuwając komercjalizację na kolejne lata.
Dalsze ukierunkowanie badań
Planuję przeprowadzić precyzyjne dociekania dotyczące spadek przewodności cieplnej krzemu w ultra-cienkich nanosheetach z powodu rozpraszania akustycznych fononów na granicach oraz zebrać szczegółowe przewidywania dla węzłów komercyjnych Intel 14A i Samsung SF1.4.
aminext.blog
Chip Giants' Showdown: TSMC, Samsung, Intel Tech Deep Dive - AmiNext
trendforce.com
[News] Battle of the Titans in the Angstrom Era – TSMC's A16 Competes with Intel's 14A and Samsung's SF1.4 - TrendForce
cyberraiden.wordpress.com
2nm Semiconductor Fabrication: Technical Hurdles in TSMC N2, Samsung SF2, and Intel 18A - Cyber Raiden
medium.com
Demystifying VLSI Technology Nodes: From Basics to the Cutting Edge (2026 Update) | by Dhruvesh Kamble | Medium
semiwiki.com
Samsung 2nm Process Technology Wiki - SemiWiki
scribd.com
20240911101100 AI賦能，半導體晶片技術與產業變革| PDF - Scribd
intel.com
Semiconductor Manufacturing Process | Intel 14A, 18A, and 3
anysilicon.com
Intel Begins Work on 10A and 7A Process Nodes as 14A Roadmap Moves Toward Key PDK Release - AnySilicon
arxiv.org
[2204.01423] Phonon heat capacity and self-heating normal domains in NbTiN nanostrips
Ewolucja architektury Samsung SF1.4 i litografia High-NA
Syntetyzuję zebrane parametry techniczne dla nadchodzącego węzła Samsung SF1.4 (1.4nm). Odkrywam, że producent planuje zwiększyć liczbę ułożonych pionowo nanosheetów z 3 do 4 w stosie MBCFET, co pozwoli na wzrost prądu przewodzenia (Ion) przy zachowaniu niskiego prądu ucieczki. Zauważam również, że procesy generacji 1.4nm (zarówno Intel 14A, jak i Samsung SF1.4) będą kluczowym punktem przejścia na litografię EUV o wysokiej aperturze numerycznej (High-NA EUV, 0.55 NA), co pozwoli na skokowe zwiększenie gęstości upakowania tranzystorów.
Przewodność cieplna w skali nanometrycznej
Rozwiązuję złożony problem degradacji właściwości termicznych w ultracienkich strukturach krzemowych. Analizując fizykę przenoszenia ciepła, dostrzegam, że przy grubości nanosheeta rzędu 5–7 nm przewodność cieplna krzemu gwałtownie spada z ok. 148 W/(m·K) dla materiału masowego do zaledwie 15–30 W/(m·K). Wynika to z przestrzennego uwięzienia fononów oraz ich intensywnego rozpraszania na granicach fazowych z dielektrykiem bramki i przekładkami wewnętrznymi.
Finalizacja syntezy i zestawienia zbiorczego
Przystępuję do końcowego opracowania i syntezy zebranych danych. Przygotowuję kompleksowe zestawienie porównawcze architektury GAAFET, sieci zasilania od spodu oraz parametrów fizycznych dla procesów TSMC, Intela i Samsunga w węzłach 2nm i 1.4nm, uwzględniając bilans zysków wydajnościowych oraz wyzwań termomechanicznych.
Wstępne badania przyniosły mnóstwo informacji. Przeglądam je i porządkuję. Dzięki temu całość będzie płynna i uwzględni wszystkie kluczowe punkty, o które prosiłeś.
To jest to! Wszystko zbieram w całość. Zapisuję ostatnie myśli, dopracowuję każdy szczegół i upewniam się, że daję z siebie wszystko.