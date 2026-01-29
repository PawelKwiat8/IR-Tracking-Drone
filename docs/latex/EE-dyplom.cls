\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{EE-dyplom}[2026/01/28 Szablon Pracy Dyplomowej]

% Bazujemy na klasie article (opcjonalnie można zmienić na 'report' dla rozdziałów)
\LoadClass[12pt, a4paper]{article}

% --- PAKIETY PODSTAWOWE ---
\RequirePackage[utf8]{inputenc}
\RequirePackage[T1]{fontenc}
\RequirePackage{graphicx}   % Obsługa grafik
\RequirePackage{geometry}   % Ustawienia marginesów
\RequirePackage{mathptmx}   % Czcionka Times New Roman (lepsza obsługa matematyki)
\RequirePackage{caption}    % Formatowanie podpisów
\RequirePackage{microtype}  % Poprawa łamania wierszy i optyczna korekta marginesów
\frenchspacing              % Standardowe odstępy po kropkach w j. polskim
\setlength{\emergencystretch}{3em} % Pomaga uniknąć "Overfull \hbox" przy trudnych słowach

% --- USTAWIENIA MARGINESÓW ---
\geometry{
 a4paper,
 margin=25mm
}

% --- ZMIENNE DO STRONY TYTUŁOWEJ ---
\def\@uczelnia{Politechnika Warszawska}
\newcommand{\uczelnia}[1]{\def\@uczelnia{#1}}

\def\@wydzial{}
\newcommand{\wydzial}[1]{\def\@wydzial{#1}}

\def\@kierunek{}
\newcommand{\kierunek}[1]{\def\@kierunek{#1}}

\def\@specjalnosc{}
\newcommand{\specjalnosc}[1]{\def\@specjalnosc{#1}}

\def\@album{}
\newcommand{\album}[1]{\def\@album{#1}}

\def\@promotor{}
\newcommand{\promotor}[1]{\def\@promotor{#1}}

\def\@rodzajpracy{Praca dyplomowa inżynierska}
\newcommand{\rodzajpracy}[1]{\def\@rodzajpracy{#1}}

% --- WYGLĄD STRONY TYTUŁOWEJ ---
\renewcommand{\maketitle}{%
  \begin{titlepage}
    \begin{center}
      \vspace*{0.5cm}
      
      % Główne logo z nazwą uczelni i wydziału (jak w załączonym obrazku)
      \IfFileExists{../mel-ikona-wpisu.jpg}{
        \includegraphics[width=0.4\textwidth]{../mel-ikona-wpisu.jpg}
      }{
        {\Large \bfseries \@uczelnia \par}
        {\large \@wydzial \par}
        \vspace{1cm}
        \fbox{\parbox[c][2cm]{0.6\textwidth}{\centering \textbf{[TU WSTAW LOGO MEL]} \\ (Plik: docs/mel-ikona-wpisu.jpg)}}
      }
      
      \vspace{2.5cm}
      
    
      
      \vspace{2.5cm}
      
      {\Huge \bfseries \@rodzajpracy \par}
      
      \vspace{1.5cm}
      
      {\LARGE \bfseries \@title \par}
      
      \vfill
      
      {\Large \bfseries \@author \par}

      
      \vspace{1.5cm}
      
      {\large Promotor pracy: \par}
      {\large \bfseries \@promotor \par}
      
      \vspace{2cm}
      
      {\large WARSZAWA \@date \par}
      
    \end{center}
  \end{titlepage}
}