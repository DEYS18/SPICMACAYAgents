# Test with ten real posters

The ten posters a coordinator sent (one from June, nine from September and October 2026) were filed together with **Several posters at once**, end to end:

1. Chosen in the assistant, read, merged and grouped.
2. Checked against the directory and the portal.
3. Resolved by tapping.
4. Filed and emailed.
5. Two Requests for Payment chosen and sent.

This ran in Chromium against a copy of the portal schema with a realistic directory, and it is also an automated test (`tests/test_real_posters.py`). Screenshots and the six generated APRs are in `docs/real_poster_test/`.

**One step was not real:** reading the images. This sandbox has no OpenAI key, so the vision step was replaced by what each poster says, written down exactly as printed (`tests/real_world.py`). On your server GPT-4o reads the images with the prompt in `app/skills/output_skills.py`; everything after that is what was tested. Dense posters such as the Nalanda Virasat are where the model is most likely to miss or merge a session, and the plan card is where you catch it before filing.

## What the assistant made of them

| Program | Posters | Events | First status | What it needed |
|---|---|---|---|---|
| Virasat 2026: Nalanda Public School | 1, 2 | 11: three concerts, seven workshops (9 to 11 Sep), yoga | Needs input | Five names not in the directory. Yoga was unticked; the four artisans were added as provisional artists |
| Circuit: Suranjana Bose | 3, 4 | 2: Heritage International School (8 Sep, 11 am) and TIFR (8 Sep, 6 pm) | Ready | |
| Virasat 2026: VNIT Nagpur | 5 | 2: Kalapini Komkali workshop (24 Sep; 25 to 26 Sep) | Ready | |
| Parveen Sultana at BITS Pilani Mumbai Campus | 7 | 1 | Needs input | The Mumbai campus is not in the directory; added (Kalyan, Maharashtra) |
| Lalgudi Vijayalakshmi at TISS | 8, 9 | 1 | Ready | |
| Rupak Kulkarni at St. Mary's ICSE School | 10 | 1 | Ready | |

Also handled:
- **Duplicates.** Poster 2 is the Nalanda Virasat's own 9 Sep concert, so it was merged. The posters disagree on the start time (1:00 or 1:10 pm); 1:00 pm was used and flagged. Posters 8 and 9 are one concert; the accompanists come from poster 9.
- **No APR needed.** Poster 6 (the Shatranj Ke Khilari screening) has no performing artist.
- **Circuit and Virasat overlap.** The circuit notes that Suranjana Bose's 9 Sep concert is filed with the Nalanda Virasat.

**Result:**
- **Filed:** APRs 208 to 213 (numbered like the portal's own, after its newest APR 207), which wrote 32 portal rows and 32 APR lines, plus 3 program records (the two Virasats and the circuit). Multi-day workshops are one row per day: Nalanda's seven workshops over 9 to 11 Sep give 21 rows plus 3 concerts, and VNIT's workshop gives 24, 25 and 26 Sep. (The first run, before that decision, wrote 17.)
- **Emailed:** each APR went to the coordinator (a dry run here) with its posters attached.
- **Other emails:** four Artist Care Group notices for the provisional artists, and three thank-yous to artists whose email is on file.
- **Requests for Payment:** TISS (Rs 15,000) and BITS (Rs 25,000) were chosen, previewed and sent.
- **No double filing:** uploading the same posters again files nothing; every event is recognised as already in the portal.

**Matching that worked:**
- **Spelling:** Parween to Parveen; Bageshree to Bageshri; B C Manjunath to B.C. Manjunath.
- **Titles:** Begum, Ustad, Pandit, Vid., Shri, Smt. and Dr. are all handled.
- **Middle names:** Dr. Rupali Shrikant Desai matches Dr. Rupali Desai, and not Rupali Deshpande.
- **Same name, different art form:** Ustad Akram Khan on tabla, not the Kathak dancer of the same name.
- **Institutions:**
  - VNIT to Visvesvaraya National Institute of Technology;
  - Tata Institute of Social Science to Sciences;
  - Nalanda Public School in Mulund, not Pune;
  - St. Mary's ICSE School in Koparkhairane (from its address), not St. Mary's School, Pune;
  - Heritage International School in Kalyan East.

## Problems the test found, now fixed

1. **Same-name institutions.** With two schools of the same name, the matching city's bonus was erased because scores were capped before ranking, so the right school looked tied with its namesake. Ranking now uses the uncapped score.
2. **Module wording.** Posters word modules freely ("Hindustani Vocal Recital", "Classic Movie Screening", "Karnataka Classical Music Concert"). These now map to the portal's modules.
3. **Middle names on posters** that the directory doesn't store now match.
4. **Multi-day workshops** have an end date, printed as "09-Sep-2026 to 11-Sep-2026".
5. **Localities** such as Koparkhairane and Kalyan East are matched against institution addresses, not only the city.
6. **Weak suggestions.** For people not in the directory, far-fetched suggestions such as a deceased maestro for a craftsperson are no longer offered.
7. **APR layout details:**
   - the repeated subtitle is gone;
   - the "Audience (Other)" heading no longer breaks;
   - the coordinator's name is capitalised;
   - the host club no longer appears as the coordinator's chapter;
   - an artist appearing twice in a Virasat lists both events.
8. **Dry-run emails** with the same subject no longer overwrite each other.

## Decisions

- **Contribution amounts: decided.** Nothing is added to the portal database for now; the amounts stay in the Request for Payment.
- **Concerts inside a Virasat: agreed.** They are filed with the Virasat; untick them in the card when a chapter files them separately.
- **Multi-day workshops: decided.** One portal row per day, now implemented.
