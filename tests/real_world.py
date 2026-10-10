"""The ten real posters a coordinator sent (September to October 2026, plus one from June), written
down exactly as printed, i.e. what the vision model should return for each image. The directory
seed is realistic: spellings differ from the posters, two artists share a name, two schools share
a name, the craft artisans and the new BITS Mumbai campus are not in the directory yet."""

ARTISTS = [  # tid, name, art_form, city, state, email, phone, bank, account, ifsc
    (100, 'Suranjana Bose', 'Hindustani Vocal', 'Mumbai', 'Maharashtra', 'suranjana@example.com', '', '', '', ''),
    (101, 'Milind Naik', 'Tabla', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (102, 'Vinod Padge', 'Harmonium', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (103, 'Pt. Shailesh Bhagwat', 'Shehnai', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (104, 'Dr. Rupali Desai', 'Kathak', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (105, 'Bageshri Sane', 'Hindustani Vocal', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (106, 'Arup Malakar', 'Sholapith Craft', 'Kolkata', 'West Bengal', '', '', '', '', ''),
    (107, 'Kalapini Komkali', 'Hindustani Vocal', 'Dewas', 'Madhya Pradesh', 'kalapini@example.com', '', '', '', ''),
    (108, 'Parveen Sultana', 'Hindustani Vocal', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (109, 'Akram Khan', 'Tabla', 'New Delhi', 'Delhi', '', '', '', '', ''),
    (110, 'Srinivas Acharya', 'Harmonium', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (111, 'Lalgudi Vijayalakshmi', 'Violin', 'Chennai', 'Tamil Nadu', '', '', '', '', ''),
    (112, 'H. Sivaramakrishnan', 'Ghatam', 'Bengaluru', 'Karnataka', '', '', '', '', ''),
    (113, 'B.C. Manjunath', 'Mridangam', 'Bengaluru', 'Karnataka', '', '', '', '', ''),
    (114, 'Rupak Kulkarni', 'Flute', 'Mumbai', 'Maharashtra', '', '', '', '', ''),
    (115, 'Rupali Deshpande', 'Hindustani Vocal', 'Pune', 'Maharashtra', '', '', '', '', ''),
    (116, 'Akram Khan', 'Kathak', 'London', '', '', '', '', '', ''),
]
INSTITUTIONS = [  # sid, name, city, state, email, coordinator, phone, address
    (100, 'Nalanda Public School', 'Mumbai', 'Maharashtra', 'nps.mulund@example.in', 'Principal', '', 'Mulund West, Mumbai'),
    (101, 'Nalanda Public School', 'Pune', 'Maharashtra', 'nps.pune@example.in', '', '', 'Kothrud'),
    (102, 'Heritage International School', 'Kalyan', 'Maharashtra', 'his@example.in', '', '', 'Katemanivli, Kalyan East'),
    (103, 'Tata Institute of Fundamental Research', 'Mumbai', 'Maharashtra', 'spic.macay.tifr@gmail.com', '', '', 'Homi Bhabha Road, Colaba'),
    (104, 'Visvesvaraya National Institute of Technology', 'Nagpur', 'Maharashtra', 'spicmacay@vnit.ac.in', '', '', 'South Ambazari Road'),
    (105, 'Tata Institute of Social Sciences', 'Mumbai', 'Maharashtra', '', '', '', 'V.N. Purav Marg, Deonar'),
    (106, "St. Mary's ICSE School", 'Navi Mumbai', 'Maharashtra', 'stmarys@example.in', '', '', 'Sector 9, Koparkhairane'),
    (107, "St. Mary's School", 'Pune', 'Maharashtra', '', '', '', 'Camp'),
]


def seed_real_world(db):
    for t in ARTISTS:
        db.execute_query('INSERT INTO artists_list (tid, name, art_form, city, enter_state, email, phone, bank_name, account_number, '
                         'ifsc_code, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)', t, commit=True)
    for sid, name, city, state, email, coord, phone, addr in INSTITUTIONS:
        db.execute_query('INSERT INTO institution_list (sid, institution_name, city, state, email, name_of_the_coordinator, phone, address, '
                         'status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)', (sid, name, city, state, email, coord, phone, addr), commit=True)
    return db


_SURANJANA = {'name': 'Vidushi Suranjana Bose', 'art_form': 'Hindustani Vocal'}
_SURANJANA_ACC = [{'name': 'Milind Naik', 'art_form': 'Tabla'}, {'name': 'Vinod Padge', 'art_form': 'Harmonium'}]
_NPS = {'institution': 'Nalanda Public School', 'city': 'Mulund', 'state': 'Maharashtra'}


def _workshop(artist, art_form):
    return dict(_NPS, date='2026-09-09', end_date='2026-09-11', start_time='09:30', end_time='12:30', module='Workshop',
                artist=artist, art_form=art_form)


POSTERS = [
    ('PHOTO-2026-09-05-09-28-35.jpg', {
        'program_type': 'virasat', 'title': 'Virasat 2026', 'module': 'Workshops, intensives and concerts',
        'chapter': 'Nalanda Public School, Mulund SPIC MACAY Chapter',
        'host_institution': {'name': 'Nalanda Public School', 'city': 'Mulund', 'state': 'Maharashtra'},
        'main_artist': None, 'accompanying': [],
        'events': [
            dict(_NPS, date='2026-09-09', start_time='13:10', end_time='14:50', module='Concert', artist='Vidushi Suranjana Bose', art_form='Hindustani Vocal'),
            dict(_NPS, date='2026-09-10', start_time='13:10', end_time='14:50', module='Concert', artist='Pandit Shailesh Bhagwat', art_form='Shehnai'),
            dict(_NPS, date='2026-09-11', start_time='13:10', end_time='14:50', module='Concert', artist='Dr. Rupali Shrikant Desai', art_form='Kathak'),
            _workshop('Smt. Bageshree Sane', 'Hindustani Vocal'), _workshop('Shri. Arup Malakar', 'Sholapith craft'),
            _workshop('Smt. Rubi Devi', 'Sikki Grass Weaving'), _workshop('Dr. Rupali Shrikant Desai', 'Kathak'),
            _workshop('Dr. Sneh Gangal', 'Miniature Painting (Kangra style)'), _workshop('Shri. Lal Chand Chhipa', 'Bagru Block Printing'),
            _workshop('Shri. Venkat R Singh', 'Pardhan-Gond Painting'),
            dict(_NPS, date='2026-09-09', end_date='2026-09-11', start_time='07:10', end_time='08:55', module='Yoga', artist='Ambika Yog Kutir', art_form='Yoga'),
        ], 'contacts': [], 'notes': 'Stalls 12:30 to 1:00 pm and 1:30 to 3:00 pm'}),
    ('PHOTO-2026-09-06-14-24-09.jpg', {
        'program_type': 'single', 'title': None, 'module': 'Hindustani Vocal Recital', 'chapter': None, 'main_artist': _SURANJANA,
        'accompanying': _SURANJANA_ACC, 'events': [dict(_NPS, date='2026-09-09', start_time='13:00')], 'contacts': []}),
    ('PHOTO-2026-09-06-14-24-10.jpg', {
        'program_type': 'single', 'module': 'Hindustani Vocal Recital', 'main_artist': _SURANJANA, 'accompanying': _SURANJANA_ACC,
        'events': [{'date': '2026-09-08', 'start_time': '11:00', 'institution': 'Heritage International School', 'city': 'Kalyan East',
                    'state': 'Maharashtra', 'venue': 'Katemanivli'}]}),
    ('PHOTO-2026-09-06-14-24-11.jpg', {
        'program_type': 'single', 'module': 'Hindustani Vocal Recital', 'chapter': 'Tata Institute of Fundamental Research, Mumbai',
        'host_institution': {'name': 'Tata Institute of Fundamental Research', 'city': 'Mumbai'}, 'main_artist': _SURANJANA,
        'accompanying': _SURANJANA_ACC,
        'events': [{'date': '2026-09-08', 'start_time': '18:00', 'institution': 'Tata Institute of Fundamental Research', 'city': 'Mumbai',
                    'venue': 'Homi Bhabha Auditorium Foyer'}],
        'notes': 'Non-TIFR guests register at https://tinyurl.com/4b4cfm6f; details spic.macay.tifr@gmail.com'}),
    ('PHOTO-2026-09-28-09-15-28.jpg', {
        'program_type': 'virasat', 'title': 'Virasat 2026', 'module': 'Hindustani Vocal Workshop', 'chapter': 'VNIT Nagpur Chapter',
        'host_institution': {'name': 'VNIT Nagpur', 'city': 'Nagpur', 'state': 'Maharashtra'},
        'main_artist': {'name': 'Vid. Kalapini Komkali', 'art_form': 'Hindustani Vocal'}, 'accompanying': [],
        'events': [{'date': '2026-09-24', 'start_time': '14:00', 'end_time': '17:00', 'institution': 'VNIT Nagpur', 'city': 'Nagpur',
                    'venue': 'Seminar Hall, First floor, Department of Civil Engineering', 'module': 'Workshop'},
                   {'date': '2026-09-25', 'end_date': '2026-09-26', 'start_time': '09:00', 'end_time': '12:00', 'institution': 'VNIT Nagpur',
                    'city': 'Nagpur', 'venue': 'Seminar Hall, First floor, Department of Civil Engineering', 'module': 'Workshop'}]}),
    ('PHOTO-2026-09-28-09-15-38.jpg', {
        'program_type': 'virasat', 'title': 'Virasat 2026', 'module': 'Classic Movie Screening', 'chapter': 'VNIT Nagpur Chapter',
        'main_artist': None,
        'events': [{'date': '2026-09-26', 'start_time': '14:30', 'institution': 'VNIT Nagpur', 'city': 'Nagpur', 'venue': 'Auditorium',
                    'module': 'Cinema Classic', 'artist': None}], 'notes': 'Shatranj Ke Khilari'}),
    ('PHOTO-2026-09-28-09-52-51.jpg', {
        'program_type': 'single', 'module': 'Hindustani Vocal Concert', 'chapter': 'Heritage Club of BITSoM',
        'main_artist': {'name': 'Begum Parween Sultana', 'art_form': 'Hindustani Vocal'},
        'accompanying': [{'name': 'Ustad Akram Khan', 'art_form': 'Tabla'}, {'name': 'Pandit Shrinivas Acharya', 'art_form': 'Harmonium'}],
        'events': [{'date': '2026-09-30', 'start_time': '18:00', 'end_time': '20:00', 'institution': 'BITS Pilani Mumbai Campus',
                    'city': 'Kalyan', 'venue': 'Village Kamba'}],
        'contacts': [{'name': 'Swathi', 'phone': '7338437147'}, {'name': 'Tanya', 'phone': '9742351581'}], 'notes': 'Padma Bhushan awardee'}),
    ('PHOTO-2026-10-04-12-08-18.jpg', {
        'program_type': 'single', 'module': 'Karnataka Classical Music Concert', 'chapter': 'TISS SPIC MACAY Heritage Club',
        'main_artist': {'name': 'Lalgudi Vijayalakshmi', 'art_form': 'Violin'}, 'accompanying': [],
        'events': [{'date': '2026-10-05', 'start_time': '16:00', 'end_time': '18:00', 'institution': 'Tata Institute of Social Science',
                    'city': 'Mumbai', 'venue': 'Quadrangle, Main Campus'}], 'notes': 'World Mental Health Week'}),
    ('PHOTO-2026-10-05-08-47-59.jpg', {
        'program_type': 'single', 'module': 'Karnataka Classical Music Concert', 'chapter': 'TISS SPIC MACAY Heritage Club',
        'main_artist': {'name': 'Lalgudi Vijayalakshmi', 'art_form': 'Violin'},
        'accompanying': [{'name': 'H Sivaramakrishnan', 'art_form': 'Ghatam'}, {'name': 'B C Manjunath', 'art_form': 'Mridangam'}],
        'events': [{'date': '2026-10-05', 'start_time': '16:00', 'end_time': '18:00', 'institution': 'Tata Institute of Social Science',
                    'city': 'Mumbai', 'venue': 'Quadrangle, Main Campus'}]}),
    ('PHOTO-2026-06-11-19-41-03.jpg', {
        'program_type': 'single', 'module': 'Flute concert', 'chapter': "Heritage Club of St. Mary's ICSE School, Koparkhairane",
        'main_artist': {'name': 'Pt. Rupak Kulkarni', 'art_form': 'Flute'}, 'accompanying': [],
        'events': [{'date': '2026-06-12', 'start_time': '09:00', 'end_time': '10:30', 'institution': "St. Mary's ICSE School",
                    'city': 'Koparkhairane', 'venue': 'Auditorium'}]}),
]
UNKNOWN_ARTISANS = [('Smt. Rubi Devi', 'Sikki Grass Weaving'), ('Dr. Sneh Gangal', 'Miniature Painting (Kangra style)'),
                    ('Shri. Lal Chand Chhipa', 'Bagru Block Printing'), ('Shri. Venkat R Singh', 'Pardhan-Gond Painting')]
