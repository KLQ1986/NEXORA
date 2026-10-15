"""The controlled vocabulary (design 2026-10-14, section 6): one Vietnamese name for each thing, so that a description, a label
and a search all say the same word for it.

Three uses:
- the labels of Apple's picture classifier and sound classifier get their Vietnamese names (`VISION`, `SOUND_KINDS`);
- the words a model answers with are brought to their canonical form ("cây cối", "cây xanh" are "cây") by `canonical`;
- an English word a model slips into a Vietnamese answer ("countryside") is turned into Vietnamese by `vietnamese`, or named as
  foreign so that the answer can be flagged.

Changing a name here changes the version of the vocabulary, which is part of what a description is keyed on.
"""
import re
import unicodedata

VERSION = "1"

SHOT_SIZES = ("cực toàn", "toàn", "trung", "cận", "đặc tả")
ANGLES = ("ngang tầm", "từ trên xuống", "từ dưới lên", "trên cao", "nghiêng")
VIEWPOINTS = ("khách quan", "góc nhìn nhân vật", "qua vai", "tự quay")
PLACES = ("trong nhà", "ngoài trời")
TIMES = ("ngày", "đêm", "bình minh hoặc hoàng hôn", "không rõ")
CONTENT_KINDS = ("hành động đời sống", "người nói trước máy", "phong cảnh", "chi tiết cận", "màn hình", "đồ hoạ hoặc chữ", "timelapse")
RELATIONS = ("cầm", "mặc", "đeo", "ngồi trên", "đứng cạnh", "đặt trên", "ở trong", "đi vào", "đi ra", "nhìn vào", "nói với", "đưa cho", "dùng")
EMOTIONS = ("vui", "buồn", "ngạc nhiên", "giận", "sợ", "trung tính")
GENRES = ("vlog du lịch", "ẩm thực", "hướng dẫn", "phỏng vấn", "sự kiện", "giới thiệu sản phẩm", "phong cảnh", "đời sống", "cảnh chèn", "quay màn hình")
# Things often filmed in Vietnam that a vision model tends to call by a vaguer name ("thuyền nhỏ", "cây cỏ", "xe"). Offered to it
# as names to use only when the thing is plainly seen; never as a list of what to find.
LOCAL_NAMES = ("thuyền thúng", "ghe", "tàu cá", "xe điện du lịch", "xe máy", "xích lô", "nón lá", "áo dài", "hoa giấy", "hoa sứ", "cây dừa", "cây phi lao",
               "cây bàng", "rau muống biển", "ruộng lúa", "mái lá", "mái ngói đỏ", "nhà sàn", "đèn lồng", "gánh hàng rong", "chợ", "quán cóc", "bánh mì", "phở")
LIGHT_DIRECTIONS = ("trước", "bên", "sau", "trên", "không rõ")

# Apple's picture classifier, by its identifiers. Labels not listed keep their English name in `tags_en` and stay searchable
# by meaning (the text embedding is multilingual), but are never shown as Vietnamese words.
VISION = {
    "outdoor": "ngoài trời", "interior_room": "trong nhà", "interior_shop": "trong cửa hàng", "sky": "bầu trời", "blue_sky": "trời xanh",
    "cloudy": "trời nhiều mây", "night_sky": "trời đêm", "sunset_sunrise": "hoàng hôn", "sun": "mặt trời", "moon": "mặt trăng", "rainbow": "cầu vồng",
    "haze": "sương mù", "storm": "bão", "snow": "tuyết", "ice": "băng", "fire": "lửa", "flame": "ngọn lửa", "lightning": "tia chớp", "daytime": "ban ngày",
    "plant": "cây", "tree": "cây", "shrub": "bụi cây", "foliage": "tán lá", "vegetation": "cây cỏ", "grass": "cỏ", "flower": "hoa", "blossom": "hoa nở",
    "palm_tree": "cây dừa", "forest": "rừng", "jungle": "rừng rậm", "garden": "vườn", "park": "công viên", "decorative_plant": "cây cảnh", "bonsai": "bonsai",
    "orchid": "hoa lan", "rose": "hoa hồng", "lily": "hoa ly", "sunflower": "hoa hướng dương", "lotus": "hoa sen", "moss": "rêu", "branch": "cành cây",
    "land": "đất", "path": "lối đi", "trail": "đường mòn", "road": "con đường", "road_other": "con đường", "street": "đường phố", "dirt_road": "đường đất",
    "sidewalk": "vỉa hè", "alley": "con hẻm", "crosswalk": "vạch qua đường", "bridge": "cây cầu", "tunnel": "đường hầm", "stairs": "cầu thang",
    "mountain": "núi", "hill": "đồi", "cliff": "vách đá", "canyon": "hẻm núi", "cave": "hang động", "rocks": "đá", "sand": "cát", "desert": "sa mạc",
    "beach": "bãi biển", "shore": "bờ biển", "ocean": "biển", "water": "nước", "water_body": "mặt nước", "lake": "hồ", "river": "sông", "creek": "suối",
    "waterfall": "thác nước", "waterways": "kênh rạch", "wetland": "đầm lầy", "island": "đảo", "harbour": "bến cảng", "pier": "cầu tàu", "dock": "bến tàu",
    "underwater": "dưới nước", "pool": "hồ bơi", "fountain": "đài phun nước", "rice_field": "ruộng lúa", "farm": "nông trại", "agriculture": "nông nghiệp",
    "orchard": "vườn cây ăn quả", "vineyard": "vườn nho", "greenhouse": "nhà kính", "wheat": "lúa mì",
    "structure": "công trình", "building": "toà nhà", "house_single": "ngôi nhà", "domicile": "nhà ở", "apartment": "chung cư", "skyscraper": "nhà cao tầng",
    "cityscape": "cảnh thành phố", "roof": "mái nhà", "window": "cửa sổ", "door": "cửa ra vào", "fence": "hàng rào", "balcony": "ban công",
    "porch": "hiên nhà", "patio": "sân hiên", "gazebo": "chòi nghỉ", "pergola": "giàn hoa", "tent": "lều", "temple": "chùa", "tower": "tháp",
    "castle": "lâu đài", "monument": "tượng đài", "statue": "tượng", "ruins": "phế tích", "arch": "mái vòm", "storefront": "mặt tiền cửa hàng",
    "restaurant": "nhà hàng", "bar": "quầy bar", "museum": "bảo tàng", "library": "thư viện", "hospital": "bệnh viện", "classroom": "lớp học",
    "office_supplies": "văn phòng phẩm", "kitchen": "nhà bếp", "kitchen_room": "nhà bếp", "kitchen_countertop": "mặt bếp", "living_room": "phòng khách",
    "bedroom": "phòng ngủ", "bathroom": "phòng tắm", "dining_room": "phòng ăn", "parking_lot": "bãi đỗ xe", "airport": "sân bay",
    "train_station": "ga tàu", "stadium": "sân vận động", "playground": "sân chơi", "market": "chợ",
    "people": "người", "adult": "người lớn", "child": "trẻ em", "baby": "em bé", "teen": "thiếu niên", "crowd": "đám đông", "bride": "cô dâu",
    "groom": "chú rể", "wedding": "đám cưới", "celebration": "lễ kỷ niệm", "ceremony": "nghi lễ", "concert": "buổi hoà nhạc", "performance": "biểu diễn",
    "dancing": "nhảy múa", "parade": "diễu hành", "conference": "hội nghị", "graduation": "lễ tốt nghiệp", "sport": "thể thao", "hiking": "đi bộ đường dài",
    "cycling": "đạp xe", "swimming": "bơi", "surfing": "lướt sóng", "fishing": "câu cá", "camping": "cắm trại", "yoga": "yoga", "workout": "tập luyện",
    "animal": "động vật", "mammal": "thú", "dog": "chó", "canine": "chó", "cat": "mèo", "feline": "mèo", "kitten": "mèo con", "bird": "chim", "chicken": "gà",
    "poultry": "gia cầm", "duck": "vịt", "fish": "cá", "cow": "bò", "pig": "lợn", "horse": "ngựa", "goat": "dê", "buffalo": "trâu", "insect": "côn trùng",
    "butterfly": "bướm", "bee": "ong",
    "vehicle": "xe", "car": "ô tô", "automobile": "ô tô", "motorcycle": "xe máy", "bicycle": "xe đạp", "bus": "xe buýt", "truck": "xe tải",
    "train": "tàu hoả", "boat": "thuyền", "watercraft": "tàu thuyền", "canoe": "xuồng", "kayak": "thuyền kayak", "yacht": "du thuyền", "aircraft": "máy bay",
    "airplane": "máy bay", "helicopter": "trực thăng", "drone_machine": "flycam", "scooter": "xe tay ga", "rickshaw": "xích lô", "tractor": "máy cày",
    "food": "đồ ăn", "dish": "món ăn", "meat": "thịt", "beef": "thịt bò", "seafood": "hải sản", "shellfish": "sò ốc", "rice": "cơm", "noodle": "mì",
    "ramen": "mì", "soup": "canh", "bread": "bánh mì", "baked_goods": "bánh nướng", "cake": "bánh ngọt", "dessert": "món tráng miệng", "fruit": "trái cây",
    "vegetable": "rau củ", "salad": "rau trộn", "egg": "trứng", "sandwich": "bánh mì kẹp", "pizza": "pizza", "sushi": "sushi", "dumpling": "bánh bao",
    "springroll": "chả giò", "grill": "bếp nướng", "kebab": "xiên nướng", "satay": "xiên nướng", "stir_fry": "món xào", "fried_egg": "trứng chiên",
    "drink": "đồ uống", "beverage": "đồ uống", "coffee": "cà phê", "tea_drink": "trà", "juice": "nước ép", "smoothie": "sinh tố", "beer": "bia", "wine": "rượu vang",
    "cocktail": "cocktail", "bubble_tea": "trà sữa", "ice_cream": "kem", "cup": "cốc", "mug": "cốc", "drinking_glass": "ly", "bottle": "chai",
    "plate": "đĩa", "bowl": "bát", "chopsticks": "đũa", "spoon": "thìa", "fork": "dĩa", "knife": "dao", "pot_cooking": "nồi", "pan": "chảo",
    "cookware": "dụng cụ nấu ăn", "cutting_board": "thớt", "tableware": "bát đĩa", "kettle": "ấm đun", "teapot": "ấm trà",
    "table": "bàn", "chair": "ghế", "sofa": "ghế sofa", "bed": "giường", "furniture": "đồ nội thất", "lamp": "đèn", "light": "đèn", "candle": "nến",
    "book": "sách", "document": "giấy tờ", "printed_page": "trang in", "handwriting": "chữ viết tay", "sign": "biển hiệu", "street_sign": "biển báo",
    "billboards": "bảng quảng cáo", "banner": "băng rôn", "flag": "lá cờ", "screenshot": "ảnh chụp màn hình", "chart": "biểu đồ", "diagram": "sơ đồ",
    "computer": "máy tính", "laptop": "máy tính xách tay", "computer_monitor": "màn hình máy tính", "computer_keyboard": "bàn phím", "phone": "điện thoại",
    "television": "tivi", "camera": "máy ảnh", "microphone": "micro", "headphones": "tai nghe", "consumer_electronics": "đồ điện tử",
    "clothing": "quần áo", "hat": "mũ", "sunglasses": "kính râm", "eyeglasses": "kính", "bag": "túi", "backpack": "ba lô", "shoes": "giày",
    "umbrella": "ô", "jewelry": "trang sức", "watch": "đồng hồ đeo tay", "money": "tiền", "toy": "đồ chơi", "gift": "quà", "box": "hộp",
    "cardboard_box": "thùng giấy", "basket_container": "giỏ", "container": "thùng chứa", "tool": "dụng cụ", "machine": "máy móc",
    "decoration": "đồ trang trí", "painting": "tranh", "art": "nghệ thuật", "musical_instrument": "nhạc cụ", "guitar": "đàn guitar", "piano": "đàn piano",
    "drum": "trống", "lantern": "đèn lồng", "fireworks": "pháo hoa", "christmas_tree": "cây thông Noel",
}

# The kinds of sound, grouped under about forty Vietnamese names; a kind not listed here is kept but never used.
SOUND_KINDS = {
    "speech": "lời nói", "whispering": "thì thầm", "shout": "la hét", "yell": "la hét", "screaming": "la hét", "children_shouting": "trẻ em la",
    "laughter": "tiếng cười", "baby_laughter": "tiếng cười", "giggling": "tiếng cười", "belly_laugh": "tiếng cười", "chuckle_chortle": "tiếng cười",
    "crying_sobbing": "tiếng khóc", "baby_crying": "tiếng khóc", "singing": "tiếng hát", "choir_singing": "tiếng hát", "humming": "tiếng ngân nga",
    "whistling": "tiếng huýt sáo", "breathing": "tiếng thở", "cough": "tiếng ho", "sneeze": "tiếng hắt hơi", "person_walking": "tiếng bước chân",
    "person_running": "tiếng bước chân", "clapping": "vỗ tay", "applause": "vỗ tay", "cheering": "reo hò", "chatter": "tiếng trò chuyện",
    "crowd": "đám đông", "babble": "tiếng trò chuyện",
    "dog": "chó", "dog_bark": "chó sủa", "cat": "mèo", "cat_meow": "mèo kêu", "rooster_crow": "gà gáy", "chicken": "gà", "chicken_cluck": "gà",
    "fowl": "gia cầm", "duck_quack": "vịt kêu", "cow_moo": "bò", "bird": "chim hót", "bird_vocalization": "chim hót", "bird_chirp_tweet": "chim hót",
    "insect": "côn trùng", "cricket_chirp": "dế kêu", "frog_croak": "ếch kêu",
    "music": "nhạc", "guitar": "nhạc", "acoustic_guitar": "nhạc", "piano": "nhạc", "drum_kit": "nhạc", "drum": "trống", "percussion": "nhạc",
    "orchestra": "nhạc", "synthesizer": "nhạc", "bell": "tiếng chuông", "church_bell": "tiếng chuông", "wind_chime": "chuông gió",
    "wind": "gió", "wind_rustling_leaves": "lá xào xạc", "wind_noise_microphone": "gió thổi vào micro", "thunder": "sấm", "thunderstorm": "giông",
    "rain": "mưa", "raindrop": "mưa", "water": "nước", "stream_burbling": "suối chảy", "waterfall": "thác nước", "ocean": "sóng biển",
    "sea_waves": "sóng biển", "fire_crackle": "lửa tí tách", "fire": "lửa",
    "boat_water_vehicle": "thuyền", "motorboat_speedboat": "thuyền máy", "car_horn": "còi xe", "car_passing_by": "xe chạy qua", "traffic_noise": "xe cộ",
    "truck": "xe tải", "bus": "xe buýt", "motorcycle": "xe máy", "engine": "động cơ", "engine_idling": "động cơ", "engine_accelerating_revving": "động cơ",
    "rail_transport": "tàu hoả", "train": "tàu hoả", "aircraft": "máy bay", "airplane": "máy bay", "helicopter": "trực thăng", "siren": "còi báo động",
    "police_siren": "còi báo động", "ambulance_siren": "còi báo động",
    "door": "tiếng cửa", "door_slam": "tiếng cửa", "knock": "tiếng gõ", "tap": "tiếng gõ", "dishes_pots_pans": "bát đĩa va chạm",
    "cutlery_silverware": "dao dĩa", "chopping_food": "thái đồ ăn", "frying_food": "tiếng chiên xào", "boiling": "tiếng sôi", "blender": "máy xay",
    "water_tap_faucet": "vòi nước", "liquid_pouring": "rót nước", "liquid_splashing": "nước bắn", "typing": "gõ phím", "typing_computer_keyboard": "gõ phím",
    "writing": "tiếng viết", "telephone_bell_ringing": "chuông điện thoại", "ringtone": "chuông điện thoại", "camera": "tiếng máy ảnh",
    "mechanical_fan": "quạt", "air_conditioner": "điều hoà", "hammer": "tiếng búa", "power_tool": "máy khoan", "drill": "máy khoan", "saw": "tiếng cưa",
    "fireworks": "pháo hoa", "firecracker": "pháo", "click": "tiếng tách", "beep": "tiếng bíp", "whoosh_swoosh_swish": "tiếng vút",
    "silence": "im lặng",
}
# Each kind of sound has its own bar: a kind that is often heard by mistake must be surer to count. Default otherwise.
SOUND_BAR = {"lời nói": 0.6, "nhạc": 0.6, "im lặng": 0.7}
SOUND_BAR_DEFAULT = 0.5
SPEECH_KINDS = frozenset({"lời nói", "thì thầm", "la hét", "tiếng hát"})
MUSIC_KINDS = frozenset({"nhạc", "trống", "tiếng hát"})

# Words that name the same thing, to one name. Keys and values are lower case.
CANON = {
    "cây cỏ": "cây", "cây cối": "cây", "cây xanh": "cây", "cây lá": "cây", "những cái cây": "cây", "hàng cây": "cây",
    "con đường": "con đường", "đường đi": "con đường", "đường": "con đường", "đường đi bộ": "lối đi", "con đường đi bộ": "lối đi", "lối nhỏ": "lối đi",
    "lối đi bộ": "lối đi", "đường mòn": "đường mòn", "con đường nhỏ": "lối đi", "con đường bê tông": "lối đi",
    "ngôi nhà": "ngôi nhà", "nhà": "ngôi nhà", "những ngôi nhà": "ngôi nhà", "căn nhà": "ngôi nhà", "nhà lều": "nhà mái lá", "nhà có mái lá": "nhà mái lá",
    "ngôi nhà có mái lá": "nhà mái lá", "những ngôi nhà mái lá": "nhà mái lá", "mái lá": "mái lá", "mái lợp": "mái nhà",
    "nắng": "ánh nắng", "ánh nắng mặt trời": "ánh nắng", "nắng mặt trời": "ánh nắng", "ánh sáng mặt trời": "ánh nắng", "mặt trời": "mặt trời",
    "bầu trời xanh": "trời xanh", "trời": "bầu trời", "người đàn ông": "đàn ông", "một người đàn ông": "đàn ông", "người phụ nữ": "phụ nữ",
    "một người phụ nữ": "phụ nữ", "cô gái": "phụ nữ", "chàng trai": "đàn ông", "đứa trẻ": "trẻ em", "em bé": "em bé", "mọi người": "người",
    "khu nghỉ dưỡng": "khu nghỉ dưỡng", "resort": "khu nghỉ dưỡng", "khu resort": "khu nghỉ dưỡng", "ly cà phê": "cà phê", "cốc cà phê": "cà phê",
    "tách cà phê": "cà phê", "xe gắn máy": "xe máy", "xe mô tô": "xe máy", "ô-tô": "ô tô", "xe hơi": "ô tô",
}

# English that a model slips into Vietnamese, to Vietnamese. Anything else in Latin script without Vietnamese marks is foreign.
ENGLISH = {
    "countryside": "nông thôn", "resort": "khu nghỉ dưỡng", "garden": "vườn", "beach": "bãi biển", "street": "đường phố", "road": "con đường",
    "house": "ngôi nhà", "houses": "ngôi nhà", "tree": "cây", "trees": "cây", "sky": "bầu trời", "outdoor": "ngoài trời", "outdoors": "ngoài trời",
    "indoor": "trong nhà", "indoors": "trong nhà", "kitchen": "nhà bếp", "market": "chợ", "city": "thành phố", "village": "làng", "park": "công viên",
    "forest": "rừng", "mountain": "núi", "river": "sông", "lake": "hồ", "sea": "biển", "ocean": "biển", "restaurant": "nhà hàng", "cafe": "quán cà phê",
    "coffee": "cà phê", "food": "đồ ăn", "people": "người", "person": "người", "man": "đàn ông", "woman": "phụ nữ", "child": "trẻ em", "walking": "đi bộ",
    "suburb": "ngoại ô", "suburban": "ngoại ô", "pathway": "lối đi", "path": "lối đi", "villa": "biệt thự", "pool": "hồ bơi", "hotel": "khách sạn",
    # Things in a room, where a model reached for English on 0059 ("towel rack, towel").
    "towel rack": "giá treo khăn", "towel": "khăn tắm", "towels": "khăn tắm", "sink": "bồn rửa", "mirror": "gương", "toilet": "bồn cầu",
    "shower": "vòi sen", "shower head": "vòi sen", "faucet": "vòi nước", "soap": "xà phòng", "bottle": "chai", "bottles": "chai",
    "drinking glass": "cốc thuỷ tinh", "glass": "kính", "cup": "cốc", "trash can": "thùng rác", "bin": "thùng rác", "toilet paper": "giấy vệ sinh",
    "window": "cửa sổ", "door": "cửa", "lamp": "đèn", "light": "đèn", "ceiling light": "đèn trần", "shelf": "kệ", "wall": "tường", "floor": "sàn",
    "ceiling": "trần nhà", "bed": "giường", "pillow": "gối", "curtain": "rèm", "chair": "ghế", "table": "bàn", "bathroom": "phòng tắm",
    "bedroom": "phòng ngủ", "boat": "thuyền", "boats": "thuyền", "car": "ô tô", "motorbike": "xe máy", "flower": "hoa", "flowers": "hoa",
    "grass": "cỏ", "sand": "cát", "rock": "đá", "rocks": "đá", "dog": "chó", "cat": "mèo", "bird": "chim", "birds": "chim",
}
# Words of Vietnamese spelled without marks and short loanwords that are not foreign in a Vietnamese answer.
NOT_FOREIGN = frozenset({"ok", "camera", "video", "selfie", "vlog", "pizza", "sushi", "yoga", "cocktail", "sofa", "laptop", "tivi", "flycam", "gimbal",
                         "logo", "menu", "wifi", "bar", "spa", "pub", "dji", "gopro", "iphone", "tiktok", "youtube", "facebook", "ban", "con", "cho", "tay",
                         "nha", "an", "anh", "em", "mot", "hai", "ba", "bon", "nam", "sau", "bay", "tam", "chin", "muoi", "kayak", "guitar", "piano", "bonsai"})

_VIETNAMESE_MARKS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-zÀ-ỹđĐ]+")


def norm(text: str) -> str:
    return unicodedata.normalize("NFC", str(text)).strip().lower()


def canonical(term: str) -> str:
    """One name for a thing: the canonical form of a word or phrase a model used, English turned into Vietnamese."""
    t = norm(term).strip(" .,;:!?\"'")
    t = re.sub(r"^(một|những|các|vài|nhiều)\s+", "", t)
    if t in CANON:
        return CANON[t]
    if t in ENGLISH:
        return ENGLISH[t]
    return t


def canonical_list(terms) -> list[str]:
    out = []
    for term in terms or []:
        c = canonical(term)
        if c and c not in out:
            out.append(c)
    return out


def foreign_words(text: str) -> list[str]:
    """English words in a Vietnamese text: a Latin word with no Vietnamese mark that is neither a known loanword nor a mark-less
    Vietnamese syllable. Used to flag an answer that slipped into another language; a word in `ENGLISH` can be mended instead."""
    found = []
    for word in _WORD.findall(text or ""):
        low = word.lower()
        if _VIETNAMESE_MARKS.search(low) or low in NOT_FOREIGN or len(low) <= 2:
            continue
        if low in ENGLISH or (len(low) >= 4 and re.fullmatch(r"[a-z]+", low) and not _looks_vietnamese(low)):
            found.append(word)
    return found


_VI_SYLLABLE = re.compile(r"^(b|c|ch|d|g|gh|gi|h|k|kh|l|m|n|ng|ngh|nh|p|ph|qu|r|s|t|th|tr|v|x)?(a|ai|ao|au|ay|e|eo|i|ia|iu|o|oa|oai|oay|oe|oi|u|ua|ui|uy|uyen|uya|y|ye|yeu|uo|uoi|uou|ie|ieu|oo)(c|ch|m|n|ng|nh|p|t|i|o|u|y)?$")


def _looks_vietnamese(word: str) -> bool:
    return bool(_VI_SYLLABLE.match(word))


# Phrases first, so that "towel rack" becomes one thing and not "khăn tắm rack".
_ENGLISH_PHRASE = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(ENGLISH, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def mend(text: str) -> str:
    """Replace known English words and phrases in a Vietnamese text with their Vietnamese names."""
    return _ENGLISH_PHRASE.sub(lambda match: ENGLISH[match.group(0).lower()], text or "")


def vision_tags(classes: list, *, at_least: float = 0.3) -> tuple[list[str], list[str]]:
    """Vietnamese names of the picture labels a classifier is sure of, then the English names of the sure ones it has no name for."""
    vi, en = [], []
    for label, confidence in classes:
        if confidence < at_least:
            continue
        name = VISION.get(label)
        if name:
            if name not in vi:
                vi.append(name)
        else:
            en.append(label.replace("_", " "))
    return vi, en
