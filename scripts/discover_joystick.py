import pygame
import time
import curses # Używamy curses do stworzenia ładnego interfejsu w terminalu

def main(stdscr):
    # --- Konfiguracja curses ---
    curses.curs_set(0) # Ukryj kursor
    stdscr.nodelay(True) # Nie czekaj na naciśnięcie klawisza
    stdscr.timeout(100) # Odświeżaj co 100ms

    # --- Inicjalizacja Pygame i Joysticka ---
    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        stdscr.addstr(0, 0, "BŁĄD: Nie znaleziono żadnego joysticka (radia)! Podłącz i uruchom skrypt ponownie.")
        stdscr.refresh()
        time.sleep(5)
        return

    joystick = pygame.joystick.Joystick(0)
    joystick.init()
    
    # --- Główna pętla programu ---
    while True:
        # Sprawdź, czy użytkownik chce wyjść (naciskając 'q')
        key = stdscr.getch()
        if key == ord('q'):
            break
            
        pygame.event.pump() # Odśwież stan joysticka

        # Wyczyść ekran przed rysowaniem nowej zawartości
        stdscr.clear()

        # --- Wyświetlanie informacji nagłówkowych ---
        stdscr.addstr(0, 2, f"Joystick: {joystick.get_name()}", curses.A_BOLD)
        stdscr.addstr(1, 2, "Poruszaj drążkami i przełącznikami, aby zobaczyć zmiany. Naciśnij 'q' aby wyjść.")
        
        # --- Wyświetlanie stanu OSI (AXES) ---
        stdscr.addstr(3, 2, "--- OSIE (AXES) ---", curses.A_UNDERLINE)
        num_axes = joystick.get_numaxes()
        for i in range(num_axes):
            axis_val = joystick.get_axis(i)
            # Zmień kolor tła dla osi, która jest aktywnie poruszana
            attr = curses.A_REVERSE if abs(axis_val) > 0.1 else curses.A_NORMAL
            stdscr.addstr(i + 4, 4, f"Oś {i:02d}: {axis_val: 6.3f}", attr)
            
        # --- Wyświetlanie stanu PRZYCISKÓW (BUTTONS) ---
        stdscr.addstr(3, 35, "--- PRZYCISKI (BUTTONS) ---", curses.A_UNDERLINE)
        num_buttons = joystick.get_numbuttons()
        for i in range(num_buttons):
            button_val = joystick.get_button(i)
            # Zmień kolor tła dla wciśniętego przycisku
            attr = curses.A_REVERSE if button_val == 1 else curses.A_NORMAL
            stdscr.addstr(i + 4, 37, f"Przycisk {i:02d}: {button_val}", attr)

        # Odśwież ekran, aby pokazać zmiany
        stdscr.refresh()

    # Zakończenie pracy joysticka
    joystick.quit()


# Uruchomienie głównej funkcji w trybie curses
if __name__ == '__main__':
    try:
        curses.wrapper(main)
    except Exception as e:
        print(f"Wystąpił błąd: {e}")
        print("Jeśli używasz Windows, upewnij się, że zainstalowałeś bibliotekę 'windows-curses'.")