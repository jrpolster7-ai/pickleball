# Pickleball Tournament App. Full Spec for Claude Code

Client is Mrs. Rachel Carter. Builder is Joe. Default venue is the Waco Regional Tennis and Fitness Center.

Tip for Joe. Rename this file to `CLAUDE.md` in your project root and Claude Code will load it at the start of every session. Or keep this name and tell Claude Code to read it first.

---

## 0. How Claude Code should work on this project
- Read this whole file at the start of every session.
- Build one phase at a time from section 17. Do not build ahead.
- This file is the source of truth. Do not invent requirements.
- Items tagged **OPEN** need an answer from Joe. Stop and ask before building them.
- Items tagged **ASSUMED** are working defaults. Build them and keep them easy to change.
- Items tagged **DECIDED** are confirmed. Build them as written.
- Write tests for scheduling, standings, seeding, and bracket generation. These must never be wrong.
- Keep business logic out of views. Use plain Python modules such as `scheduling.py`, `standings.py`, and `brackets.py`.
- Never commit secrets. Use environment variables and a `.env.example` file.
- Before finishing a phase, run the tests and `python manage.py check`. Then summarize what changed and what Joe should try in the browser.
- Ask before adding any dependency not listed in section 15.
- Use short, friendly, plain wording in the user interface. Many users are first timers.

---

## 1. Purpose
Run pickleball events like a standard tournament. Everyone plays in a round robin. Then the top teams advance to an elimination bracket. Players register themselves, join events with a code, see their schedule, and enter their own scores. Admins control formats, courts, and brackets. Spectators view results with a separate code.

The current tool is Swish. Match its simple round viewer, where a user moves sideways from round to round. In this app that is clickable round tabs and arrow buttons, with swiping as an extra on touch screens (see section 10).

This is a website used mainly in a desktop web browser, not a phone app. See section 14.

---

## 2. Vocabulary (DECIDED)
Use these exact terms in code, templates, and the interface.

- **Level** means Beginner, Intermediate, or Advanced.
- **Division** means Men's, Women's, Mixed, or Scramble.
- **Event** means a tournament. It belongs to one Level and one Division. It can run in one day or across several weeks. Do not use "league" as a data term. The interface may say "league" for a multi-week event if Mrs. Carter prefers.
- **Round robin** is the qualifying stage before the bracket. Its results set bracket seeding.
- **Bracket** is the elimination stage, like a March Madness bracket sized to the number of teams.
- **Game** is one game played to a target score. The default is 11 points.
- **Match** is a contest between two sides, decided by games. The default is best of 3. The admin can set a match to a single game.
- **Round** is one time slot in the schedule.
- **Side** is the one or two players on one end of a match.
- **Pool** is a smaller group inside a large event that plays its own round robin.

Do not use "set" for pickleball scoring. That is tennis language.

Level and Division combinations give 12 event types. Store Levels and Divisions as seeded database rows, not hardcoded choices.

---

## 3. Roles and accounts

### Roles (DECIDED)
- **Admin.** Full control. Co-admins have identical rights to the primary admin.
- **Player.** Has an account, joins events, sees their schedule, enters scores.
- **Spectator.** Views results with a spectator code. No account needed.

### Login (DECIDED, and may change later)
- Simple username and password. No email and no phone number.
- A player logs in once and stays logged in on that device. Use a long-lived session, for example one year (ASSUMED length). Add a "stay signed in" default of on.
- Build auth so the login method can be swapped later. Use a custom user model from the start.
- No self-service password reset, because there is no email. An admin can reset any player's password.
- Profile fields are username, first name, last name, and gender (male or female).
- Admins use the same login. Use Django groups or `is_staff` for admin rights. Do not build a separate admin login.

### Admin rules (DECIDED)
- An admin can create other admins.
- Any admin can remove another admin. The app blocks removing the last remaining admin.

### Admin-added players (DECIDED)
- The admin can add players directly, even if they have no account yet.
- Each gets a claim link or claim code the admin shares by hand. The player uses it to create a username and password and claim the profile.
- Because there is no email, store these players in a `Player` model with an optional link to a user.

### Gender (DECIDED)
- Options are male or female.
- Gender is used only to check eligibility for Men's, Women's, and Mixed.
- The app blocks wrong-gender sign-ups for gendered divisions. Mixed requires one male and one female per team.
- An admin can override any placement.

---

## 4. Creating and configuring an event (admin)

### Fields
- Title
- Level and Division
- Location. Defaults to the saved Waco Regional Tennis and Fitness Center. See section 12.
- Start date, and either an end date or a number of weeks.
- Weekly day and start time for multi-week events.
- Number of courts to use, from 1 to 8 (DECIDED). 8 is the maximum.
- Number of teams (DECIDED). The admin types the number of teams in personally. It does not have to wait for registrations. Registrations fill the slots as they come in.
- Matches per team and total matches in the event (DECIDED). The admin can set either one. They are two views of the same setting, so setting one recalculates the other and both are shown. Example, 3 teams at 16 matches per team gives 24 matches total. Typing 24 total gives 16 per team. The app never caps this based on team count, so 16 is allowed even when a full round robin would be only 2 matches per team.
- ASSUMED. If the total does not divide evenly across teams, spread matches as evenly as possible so no team differs by more than one match. Show each team's count before the admin publishes the schedule.
- Games per match, either 1 or 3 (DECIDED).
- Points to win. Default 11. Admin can set another number such as 15 (DECIDED).
- Win by two, on or off (DECIDED). When on, a game continues until one side leads by two, with no upper limit unless a point cap is set.
- Optional point cap (ASSUMED).
- Minutes per match and minutes between rounds (DECIDED, see section 6).
- Whether players enter their own scores (DECIDED, per event).
- Registration mode. Admin adds everyone, players join by code, or both (DECIDED).
- Maximum participants, up to 500 (DECIDED).
- Pool size for large events (DECIDED, see section 6).
- Bracket type, single or double elimination (DECIDED, per event).
- Bracket sizing method, top seed byes or play-in matches (DECIDED, per event, see section 9).
- Third-place match, on or off (DECIDED, per event, see section 9).
- How many teams advance to the bracket. Set by the admin after the round robin ends (DECIDED).
- Player code and spectator code (see section 5).

### Status flow
Draft, Open for registration, Round robin, Bracket, Complete.

### Variables the app must handle
Number of players, matches per team, courts (1 to 8), and event length (one day or many weeks).

---

## 5. Codes and joining (DECIDED)
- Each event has its own player code and its own spectator code.
- Codes are short and easy to type. Also show each as a QR code that opens the join link.
- A player code lets a logged-in player join that event. If the player is not logged in, send them to sign up, then return them to the join step.
- A spectator code opens a read-only results view. No account is needed.
- One website serves both. The code a person enters decides whether they see the player or spectator view.
- The admin can rotate or disable either code at any time (ASSUMED).
- Players can be in several events at once, across Levels and Divisions.
- Players choose their own events. The admin can move or remove any player (DECIDED).

### Doubles teams (DECIDED)
- One player creates a team and invites a partner by username or a short team code.
- The admin can also build teams by hand.

---

## 6. Scheduling engine
Put all logic in `scheduling.py` with unit tests. It must be repeatable when given the same seed.

### Fixed-partner divisions (Men's, Women's, Mixed)
- A team is two players.
- Generate the round robin with the circle method. Add a bye when the team count is odd. Byes rotate fairly.
- If matches per team is more than one full round robin, repeat opponents as evenly as possible. Example, 3 teams with 16 matches per team.
- If matches per team is less than a full round robin, spread opponents as evenly as possible (ASSUMED).
- Generate the schedule from the admin's team count and the matches per team and total matches settings.
- Show the admin the full round robin match count as a reference next to the numbers they entered. It is a hint, not a limit.

### Scramble division (DECIDED)
- Players are individuals. There are no fixed teams.
- Each round, players are grouped into foursomes, two against two, one per court.
- The goal is that each player partners with and plays against as many different people as possible.
- The admin sets the number of rounds.
- If the player count is not divisible by 4, extra players sit out. Sit-outs rotate fairly.
- Standings are per player, not per team.
- There is no bracket for Scramble in version 1. The top ranked player wins.

### Pools for large events (DECIDED)
- The admin sets pool size, such as 6. The app works out the number of pools.
- Teams are snake-seeded into pools.
- Each pool plays its own round robin.
- Bracket seeding then crosses all pools.

### Courts, rounds, and time (DECIDED)
- Matches in a round are limited by the number of courts the admin selects.
- If there are more matches than courts, extra matches move to the next time slot.
- Each match gets a court number and a start time.
- A side cannot be scheduled twice in one round.
- The app generates start times from the admin's minutes per match and minutes between rounds.
- The admin can edit match length and can edit any round or match start time afterward.

### Multi-week events (DECIDED)
- The admin sets the number of weeks, weekly day, and time.
- Generate week 1, then clone it to the later weeks with the same matchups. The order inside a week may shuffle.
- Standings add up across all weeks.
- An optional bracket follows the final week.
- Example, a 4-week league with 6 matches every Monday.

### Changes after play starts (DECIDED)
- The schedule is not regenerated once play begins.
- The admin can mark a forfeit or withdrawal, and can edit a match by hand. Substitutes are an admin edit.
- All changes are logged.
- ASSUMED. A forfeit counts as a win for the opponent with an admin-set score, defaulting to 11 to 0 per game. Make this configurable.

---

## 7. Score entry (DECIDED)
- If the event allows player entry, either side of a match can enter the score.
- The other side must confirm.
- DECIDED (changed after Phase 8). Players settle disagreements between themselves. If one side thinks the entered score is wrong, they enter a correction, and it goes back to the other side to confirm. This can go back and forth. When both sides have entered the same score, it is final.
- Either side can choose "Ask an organizer to decide" while a score is waiting. That flags the match for the admin. Once flagged, a matching pair of entries still makes it final, or the admin sets the score.
- Scores are entered game by game, for example Game 1 is 11 to 7.
- Validate scores against the event rules. Reject impossible scores, such as 11 to 10 when win by two is on.
- Player edits lock at midnight at the end of the match's scheduled date, in America/Chicago. After that, only an admin can change the score.
- Admins can always edit. Every edit writes an audit log row with who, when, old value, and new value (ASSUMED).
- If the event does not allow player entry, only admins enter scores.

---

## 8. Standings and seeding (DECIDED)
Two ranking screens.
1. **Win and loss ranking.** Sorted by wins, then total points, then point differential.
2. **Total points ranking.** Sorted by total points scored, then wins, then point differential.

Bracket seeding order.
1. Wins, then losses
2. Total points scored
3. Point differential
4. If still tied, flag the tie for the admin, who decides directly. No automatic head-to-head rule.

Put ranking logic in `standings.py` with tests that cover ties.
Multi-week events sum all weeks.
Scramble standings are per player.

---

## 9. Brackets
- After the round robin, the admin enters how many teams advance (DECIDED).
- The app builds the bracket from the seeds in section 8 (DECIDED).
- Admin chooses single or double elimination per event (DECIDED).
- When the advancing count is not a power of 2, the admin chooses per event between two methods (DECIDED).
  - **Top seed byes.** The highest seeds skip round one.
  - **Play-in matches.** The lowest seeds play extra matches for the final spot or spots.
- DECIDED. Play-in structure. The main bracket is the largest power of 2 that fits. The teams closest to the cut play in for the last spots: the last team in plays the first team out (8 vs 9), then work outward (7 vs 10, and so on). The winner takes the higher seed's spot. Example, 10 teams advance: 8 vs 9 and 7 vs 10 play in, then an 8-team bracket. With standard seeding these are the same matches as top seed byes. Only the round names differ ("Play-in" or "Round 1").
- A third-place match is a per-event admin choice, on or off (DECIDED). ASSUMED default is on.
  - ASSUMED. In single elimination with the toggle on, the two semifinal losers play for third.
  - ASSUMED. In double elimination, third place is the loser of the losers bracket final. No separate match, so the toggle has no effect there.
- Double elimination uses winners and losers brackets. The grand final resets if the losers bracket winner wins the first final (ASSUMED).
- DECIDED. In double elimination, a team that loses an opening (play-in or round 1) match drops to the losers bracket like anyone else. Everyone is out after two losses.
- Bracket matches use the same score entry and lock rules.
- Build single elimination first. Double elimination is its own phase.

---

## 10. Screens

### Player
- Court number, time, round, and opponents for each match.
- Enter and confirm scores.
- Round robin view and both ranking screens.
- The bracket, once it exists.
- Event chat.
- In-app notices about schedule changes.

### Round viewer (match Swish)
- A "Round robin" view with a row of clickable round tabs (Round 1, Round 2, and so on) and previous and next arrow buttons. Clicking a tab or an arrow moves between rounds.
- The left and right arrow keys also move between rounds.
- Swiping sideways is an extra on touch screens. It must never be the only way to change rounds.
- On narrow screens the tab row scrolls sideways and keeps the current round in view.
- Each round lists its matches with court, time, sides, and score.
- The round robin must be visual and easy to read at the end of the event.

### Admin
- Create and edit events.
- Manage registrations, add players, and move players between events.
- Control courts, formats, and codes.
- Fix scores and view the audit log.
- Reset player passwords.
- Set how many teams advance and build the bracket.
- Manage other admins.

### Spectator (DECIDED)
- Read-only round robin, standings, and bracket.
- A round's results appear after the round is confirmed, not live and not point by point.
- ASSUMED. A round becomes visible when all its matches are confirmed or finalized by an admin. A disputed match holds the round until the admin resolves it.
- Note for Joe. Admins can still correct a score after spectators see it. This is closer to live than Mrs. Carter's original notes.
- Players show as first name and last initial.
- Spectators cannot see chat.

---

## 11. Chat (DECIDED)
- Each event has a chat room. Only players registered for that event, and admins, can post.
- The page refreshes every few seconds using HTMX polling. No WebSockets in version 1.
- Admins can delete messages.
- Users can report a message.
- No private messages and no images in version 1.

---

## 12. Saved defaults, the "memory" feature (DECIDED)
Version 1 is saved defaults, not a real AI.
- Remember the default location, the Waco Regional Tennis and Fitness Center.
- Remember the admin's last-used settings, such as courts, format, and times.
- A "copy last event" button.
- A quick-create form where the admin picks Level, Division, a start date, and a number of weeks, and everything else fills in.
- Store defaults in an `OrganizationDefaults` model so they can be edited.

Later phase, natural language creation.
- The admin types something like "Beginner mixed, Mondays in March" and the Anthropic API fills in the event.
- It must show a preview the admin confirms before anything is created.
- Needs an API key and ongoing cost. Do not build in version 1.

---

## 13. Scale (DECIDED)
- Support events of up to 500 players.
- Index event, match, and side foreign keys.
- Avoid N+1 queries on standings and the round viewer. Use `select_related` and `prefetch_related`.
- Add a management command that seeds 500 players and runs a full event as a load check.

---

## 14. Design (DECIDED that it matters)
- Desktop browser first. This is a website used mainly in a desktop web browser, not a phone app. Design the desktop layout first.
- Responsive. Pages must still work well in tablet and phone browsers. Layouts collapse to one column on narrow screens.
- Use the width on desktop. Put related panels side by side, such as settings next to codes, or a list next to its form. Keep text lines a readable length.
- Simple enough for a first-time user to understand without help.
- ASSUMED palette. Deep court green `#0F5C4D`, bright pickleball yellow-green `#C6E800`, clean white, warm gray text. Keep colors in CSS variables so they are easy to change.
- Clear court numbers and times. Controls are easy to click with a mouse and still large enough to tap on a touch screen.
- Everything works with a mouse and keyboard. Hover and focus states are visible.
- Leave a place for a logo. Mrs. Carter may supply one later.

---

## 15. Stack (DECIDED)
- Python 3.12 or newer and the current Django LTS release. Verify the version at install time.
- Django's built-in auth with a custom user model. No django-allauth, since there is no email login.
- Server-rendered Django templates with HTMX. No separate JavaScript frontend.
- Tailwind CSS. Desktop first in design, responsive for tablet and phone.
- PostgreSQL in production. SQLite is fine locally. Read `DATABASE_URL` from the environment.
- `qrcode` library for QR images.
- pytest and pytest-django.
- whitenoise and gunicorn for deployment.
- Time zone is `America/Chicago` with `USE_TZ = True`.

### Hosting
- DECIDED. Render, using `render.yaml` (web service plus PostgreSQL). Chosen in Phase 8.
- Build portable. Read all configuration from environment variables so it can move to a managed host such as Render or Railway.
- The site must be public on the internet because out-of-town spectators will use it.
- No email service is needed, since login does not use email.

---

## 16. Data model sketch
Use as a starting point. Names can change, relationships should stay.

| Model | Key fields |
|---|---|
| User | username, password, first name, last name, gender. Custom user model. |
| Player | first name, last name, gender, optional link to User, claim code |
| Level | name |
| Division | name, kind (MENS, WOMENS, MIXED, SCRAMBLE) |
| OrganizationDefaults | default location, default courts, default match format |
| Event | title, level, division, location, dates, weeks, team count, court count, matches per team, total matches, games per match, points to win, win by two, point cap, minutes per match, break minutes, players enter scores, registration mode, max participants, pool size, bracket type, bracket sizing method, third place match flag, advancing count, status, player code, spectator code |
| Registration | event, player, status, pool |
| Side | event, players (many to many). Persistent for fixed partners, created per round for Scramble. |
| Session | event, date, start time, week number |
| Round | event, session, number, start time |
| Match | event, round, court, side A, side B, stage (ROUND_ROBIN or BRACKET), bracket round, bracket slot, bracket side (WINNERS or LOSERS), status, forfeit flag |
| Game | match, number, side A points, side B points |
| ScoreSubmission | match, submitted by, confirmed by, status, locked at |
| AuditLog | actor, action, object, old value, new value, timestamp |
| ChatMessage | event, author, body, created, deleted by, reported |
| Notice | event, message, created. For in-app schedule change notices. |

---

## 17. Build plan
Finish and test each phase before starting the next. Commit after each phase.

### Phase 0. Setup
Create the Django project and apps `accounts`, `events`, `scheduling`, `scoring`, `standings`, `brackets`, `chat`, and `core`. Configure environment variables, PostgreSQL via `DATABASE_URL` with SQLite fallback, America/Chicago, whitenoise, Tailwind, pytest, `.env.example`, `.gitignore`, and a README. Add a desktop first, responsive base template. Build no features yet.
Done when the server runs, `pytest` passes, and `python manage.py check` is clean.

### Phase 1. Accounts, events, codes
Sections 3, 4, 5, and 12. Username login with long-lived sessions, custom user model, Player profiles, seeded Levels and Divisions, event create and edit, co-admin management, admin password reset, OrganizationDefaults, copy-last-event, quick-create, player and spectator codes with QR images, join by code, admin-added players with claim codes, and doubles team invites by username or team code.
Done when an admin can create an event, a player can sign up and join with a code, and a spectator code opens a placeholder page.

### Phase 2. Scheduling engine
Section 6. Circle method round robin, byes, repeated opponents, court limits, time slots and editable start times, pools by size with snake seeding, multi-week cloning, and the Scramble foursome generator. Thorough tests including odd team counts, 3 teams at 16 matches each, 500 players, and 8 courts. Admin preview screen before publishing.

### Phase 3. Score entry and locking
Section 7. Game-by-game entry, validation, opponent confirmation, dispute flagging, midnight Central lock including daylight saving tests, admin override, audit log, forfeits, and the per-event player entry setting.

### Phase 4. Standings, seeding, single elimination
Sections 8 and 9. Two ranking screens, tie flagging for the admin, advancing count, top seed byes or play-in matches, single elimination, and the optional third-place match. Tests for ties, multi-week totals, pools, and non power of 2 sizes.

### Phase 5. Double elimination
Section 9. Winners and losers brackets, grand final reset, third place from the losers bracket final. Tests for several team counts including byes.

### Phase 6. Player, spectator, and round viewer screens
Section 10. Player dashboard, round viewer with clickable round tabs and arrow buttons (swipe as an extra on touch screens), ranking screens, spectator view with the confirmed-round rule and first name plus last initial, and in-app notices.

### Phase 7. Chat
Section 11. HTMX polling, admin delete, report button, registered players and admins only.

### Phase 8. Polish, scale, deploy
Sections 13 and 14. Design pass, the 500 player load command, query fixes, and deployment steps in the README once a host is chosen.

### Phase 9. Natural language event creation (later)
Section 12. Anthropic API with a confirm-before-create preview. API key in an environment variable.

---

## 18. Open items for Joe
1. ~~Hosting. Pick a host before launch.~~ Decided in Phase 8: Render, see section 15.
2. ~~Play-in match structure for non power of 2 brackets.~~ Decided in Phase 4, see section 9.
3. Forfeit scoring in standings. Default is an 11 to 0 win per game, configurable.
4. Confirm with Mrs. Carter that spectators seeing scores after each confirmed round is close enough to "not live."
5. Confirm with Mrs. Carter that no password reset by email is acceptable. Admins reset passwords by hand.
6. Logo or brand colors from Mrs. Carter, if she has them.

## 19. Out of scope for version 1
- Payments and entry fees
- Waitlists
- Email or text notifications
- Live point-by-point scoring
- WebSockets
- Native mobile apps
- Bracket play for Scramble
- Natural language event creation
