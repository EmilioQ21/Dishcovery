"""Generate the shared Dishcovery dataset (data/dishcovery_data.json).

The core records of the Intermediate Revision (user_0001..0003, rest_0001..0005,
dish_0001..0008, rev_0001..0012) are kept unchanged so the examples in the report still
match, and a realistic Guadalajara metro dataset is generated around them.
The output is deterministic (fixed random seed): every team member gets the same ids.

    python -m dishcovery.loading.generate_data
"""
import argparse
import json
import random
from datetime import datetime, timedelta, timezone

from dishcovery import config

SEED = 42
N_USERS = 40
N_RESTAURANTS = 60

AREAS = [  # (city, neighborhood, lon, lat)
    ("Tlaquepaque", "ITESO / Periferico Sur", -103.4165, 20.6080),
    ("Tlaquepaque", "Centro Tlaquepaque", -103.3110, 20.6405),
    ("Zapopan", "Andares", -103.4130, 20.7100),
    ("Zapopan", "Chapalita", -103.3990, 20.6650),
    ("Zapopan", "Ciudad Granja", -103.4450, 20.6780),
    ("Guadalajara", "Colonia Americana", -103.3680, 20.6740),
    ("Guadalajara", "Providencia", -103.3900, 20.6930),
    ("Guadalajara", "Centro Historico", -103.3470, 20.6770),
]

# cuisine -> restaurant name parts, ambiance phrases and dish templates
# dish template: (name, description, tags, vegetarian, base_price_mxn)
CATALOG = {
    "mexican": {
        "extra": ["traditional"],
        "names": (["Tacos", "Taqueria", "Cocina", "Fonda", "Antojitos"],
                  ["El Guero", "La Chata", "Dona Lupe", "El Patron", "Los Arcos", "La Herradura", "San Juan"]),
        "ambiance": ["Busy street-food stand with plastic stools and fast service.",
                     "Family fonda with homemade food and a daily set menu.",
                     "Colorful cantina style place, good for groups."],
        "dishes": [
            ("Taco al pastor", "Marinated pork with pineapple, onion and cilantro on a corn tortilla.", ["spicy", "street food", "pork"], False, 25),
            ("Taco de suadero", "Slow cooked beef brisket taco with salsa verde.", ["beef", "street food"], False, 25),
            ("Torta ahogada", "Crusty birote roll filled with carnitas and drowned in hot chile de arbol sauce. The Guadalajara classic.", ["spicy", "pork", "local specialty"], False, 75),
            ("Chilaquiles verdes", "Fried tortilla chips in green tomatillo salsa with cream, cheese and fried egg.", ["breakfast", "comfort food"], True, 95),
            ("Enchiladas suizas", "Chicken enchiladas covered in creamy green sauce and melted cheese.", ["chicken", "creamy"], False, 130),
            ("Pozole rojo", "Hominy and pork soup with red guajillo broth, served with radish, lettuce and oregano.", ["soup", "pork", "traditional"], False, 120),
            ("Quesabirria", "Crispy tortillas filled with cheese and beef birria, served with consome for dipping.", ["beef", "cheesy", "spicy"], False, 95),
            ("Tacos de canasta", "Steamed potato and bean tacos, soft and cheap.", ["cheap", "street food"], True, 15),
            ("Tamales de rajas", "Corn masa tamales with poblano pepper strips and cheese.", ["breakfast", "cheesy"], True, 35),
        ],
    },
    "seafood": {
        "extra": ["mexican"],
        "names": (["Mariscos", "Ceviches", "La Palapa de"], ["El Capitan", "Mazatlan", "La Ola", "Puerto Vallarta", "El Pescador"]),
        "ambiance": ["Beach style place with loud banda music on weekends.",
                     "Casual seafood spot, perfect for a hot afternoon."],
        "dishes": [
            ("Aguachile verde", "Raw shrimp cured in lime juice with serrano chile, cucumber and red onion. Very spicy and fresh.", ["spicy", "seafood", "fresh"], False, 190),
            ("Tostada de ceviche", "Crispy tostada with fish ceviche, avocado and lime.", ["seafood", "fresh", "light"], False, 70),
            ("Coctel de camaron", "Shrimp cocktail in tomato sauce with avocado, onion and crackers.", ["seafood", "cold"], False, 150),
            ("Pescado zarandeado", "Whole grilled fish marinated in chile and garlic, Nayarit style.", ["seafood", "grilled", "for sharing"], False, 320),
            ("Tacos gobernador", "Shrimp and cheese tacos on corn tortillas.", ["seafood", "cheesy"], False, 110),
        ],
    },
    "japanese": {
        "extra": ["sushi"],
        "names": (["Sushi", "Ramen", "Izakaya"], ["Hana", "Kaito", "Sakura", "Koi", "Tokyo Bay", "Nami"]),
        "ambiance": ["Minimalist Japanese interior with a sushi bar.",
                     "Cozy ramen shop, quiet and good for studying with a bowl of noodles."],
        "dishes": [
            ("Salmon nigiri", "Fresh salmon over seasoned rice.", ["raw fish", "fresh"], False, 90),
            ("Spicy tuna roll", "Tuna roll with spicy mayo and cucumber.", ["spicy", "raw fish"], False, 140),
            ("Tonkotsu ramen", "Rich pork bone broth with noodles, chashu pork, soft egg and scallions.", ["soup", "pork", "comfort food"], False, 210),
            ("Vegetable gyozas", "Pan fried dumplings filled with cabbage, mushroom and ginger.", ["dumplings", "light"], True, 110),
            ("Chicken katsu curry", "Breaded chicken cutlet with Japanese curry and rice. Big portion.", ["chicken", "big portion"], False, 190),
            ("Avocado maki", "Simple avocado and cucumber roll.", ["light", "fresh"], True, 95),
        ],
    },
    "italian": {
        "extra": ["pizza"],
        "names": (["Trattoria", "Pizzeria", "Osteria"], ["Bella", "Da Marco", "Napoli", "La Nonna", "Il Forno"]),
        "ambiance": ["Romantic trattoria with candles and Italian wine.",
                     "Wood fired pizza place with a terrace, good for dates."],
        "dishes": [
            ("Fettuccine alfredo", "Fresh fettuccine in a creamy parmesan sauce.", ["pasta", "creamy"], True, 190),
            ("Pizza margherita", "Wood fired pizza with tomato, mozzarella and basil.", ["pizza", "cheesy"], True, 180),
            ("Lasagna bolognese", "Layers of pasta, beef ragu and bechamel.", ["pasta", "beef", "comfort food"], False, 220),
            ("Pizza diavola", "Pizza with spicy salami and chile flakes.", ["pizza", "spicy"], False, 210),
            ("Tiramisu", "Coffee soaked ladyfingers with mascarpone cream.", ["dessert", "coffee"], True, 110),
        ],
    },
    "healthy": {
        "extra": ["vegetarian"],
        "names": (["Green", "Fresh", "Bowl &"], ["Bowl", "Garden", "Leaf", "Roots", "Market"]),
        "ambiance": ["Bright place with plants, vegan options and cold-pressed juices.",
                     "Quick healthy lunch spot popular with students."],
        "dishes": [
            ("Quinoa bowl", "Quinoa with roasted vegetables, chickpeas and tahini dressing.", ["healthy", "vegan", "light"], True, 150),
            ("Veggie tacos", "Corn tortillas with grilled mushrooms, nopales and avocado.", ["healthy", "vegan", "cheap"], True, 85),
            ("Acai bowl", "Acai with granola, banana, strawberries and honey.", ["breakfast", "sweet", "fresh"], True, 120),
            ("Falafel wrap", "Chickpea falafel with hummus, lettuce and tomato in a wheat wrap.", ["vegan", "light"], True, 115),
            ("Grilled chicken salad", "Mixed greens with grilled chicken, avocado and seeds.", ["healthy", "chicken", "light"], False, 140),
        ],
    },
    "american": {
        "extra": ["burgers"],
        "names": (["Burger", "Smash", "Grill"], ["Joint", "Brothers", "Factory", "House", "Station"]),
        "ambiance": ["Industrial style burger bar with craft beer and sports on TV.",
                     "Casual diner with big portions and milkshakes."],
        "dishes": [
            ("Classic smash burger", "Two smashed beef patties, american cheese, pickles and house sauce.", ["beef", "big portion", "cheesy"], False, 160),
            ("Spicy chicken sandwich", "Fried chicken with habanero mayo and coleslaw.", ["chicken", "spicy"], False, 150),
            ("Loaded fries", "Fries with cheese sauce, bacon and jalapenos.", ["for sharing", "cheesy"], False, 110),
            ("Beyond veggie burger", "Plant based patty with lettuce, tomato and vegan cheese.", ["vegan", "big portion"], True, 175),
            ("Buffalo wings", "Chicken wings in hot buffalo sauce with ranch.", ["chicken", "spicy", "for sharing"], False, 170),
        ],
    },
    "chinese": {
        "extra": ["asian"],
        "names": (["Dragon", "Golden", "Panda"], ["Wok", "Palace", "Garden", "Noodle House"]),
        "ambiance": ["Fast Chinese food with generous portions.",
                     "Dim sum place with round tables for big groups."],
        "dishes": [
            ("Kung pao chicken", "Stir fried chicken with peanuts, dried chiles and Sichuan pepper.", ["chicken", "spicy"], False, 150),
            ("Pork dumplings", "Steamed pork and chive dumplings with soy dipping sauce.", ["dumplings", "pork"], False, 120),
            ("Mapo tofu", "Silken tofu in a spicy, numbing chile bean sauce.", ["spicy", "tofu"], True, 140),
            ("Fried rice", "Wok fried rice with egg, vegetables and soy sauce. Cheap and filling.", ["cheap", "big portion"], True, 90),
        ],
    },
    "korean": {
        "extra": ["asian"],
        "names": (["Seoul", "K-", "Gangnam"], ["BBQ", "Kitchen", "Street", "Pocha"]),
        "ambiance": ["Korean barbecue with grills at every table, fun for groups.",
                     "Small K-pop themed restaurant popular with students."],
        "dishes": [
            ("Bibimbap", "Rice bowl with vegetables, beef, fried egg and gochujang.", ["beef", "spicy", "healthy"], False, 170),
            ("Korean fried chicken", "Double fried chicken glazed in sweet and spicy sauce.", ["chicken", "spicy", "for sharing"], False, 190),
            ("Kimchi jjigae", "Hot kimchi stew with tofu and pork.", ["soup", "spicy", "pork"], False, 160),
            ("Tteokbokki", "Chewy rice cakes in a spicy red pepper sauce.", ["spicy", "street food"], True, 120),
        ],
    },
    "cafe": {
        "extra": ["bakery"],
        "names": (["Cafe", "Bakery", "Coffee"], ["Central", "Lab", "Origen", "Cielo", "Altura"]),
        "ambiance": ["Specialty coffee shop with fast wifi, plugs and quiet tables to study.",
                     "Bakery with fresh bread every morning and a small patio."],
        "dishes": [
            ("Concha with cafe de olla", "Sweet Mexican bread with cinnamon coffee.", ["breakfast", "sweet", "cheap"], True, 55),
            ("Avocado toast", "Sourdough toast with avocado, poached egg and chile flakes.", ["breakfast", "healthy"], True, 125),
            ("Croissant sandwich", "Butter croissant with ham and cheese.", ["breakfast", "cheesy"], False, 95),
            ("Cold brew", "Slow steeped iced coffee.", ["coffee", "cold"], True, 65),
            ("Carrot cake", "Moist carrot cake with cream cheese frosting.", ["dessert", "sweet"], True, 85),
        ],
    },
    "indian": {
        "extra": ["asian"],
        "names": (["Taj", "Bombay", "Masala"], ["Palace", "House", "Kitchen"]),
        "ambiance": ["Warm Indian restaurant with aromatic spices and a lunch buffet."],
        "dishes": [
            ("Chicken tikka masala", "Grilled chicken in a creamy spiced tomato sauce with naan.", ["chicken", "creamy", "spicy"], False, 210),
            ("Chana masala", "Chickpeas cooked in onion, tomato and garam masala.", ["vegan", "spicy"], True, 160),
            ("Palak paneer", "Fresh cheese cubes in a spinach sauce.", ["cheesy", "healthy"], True, 180),
            ("Garlic naan", "Tandoor baked flatbread with garlic butter.", ["bread", "cheap"], True, 60),
        ],
    },
}

FIRST = ["Sofia", "Diego", "Valeria", "Mateo", "Camila", "Santiago", "Regina", "Sebastian", "Ximena", "Leonardo",
         "Fernanda", "Emiliano", "Mariana", "Daniel", "Andrea", "Rodrigo", "Paula", "Alejandro", "Renata", "Pablo",
         "Lucia", "Javier", "Isabela", "Carlos", "Natalia", "Miguel", "Daniela", "Luis", "Ana", "Ricardo",
         "Carla", "Hector", "Elena", "Ivan", "Monica", "Raul", "Gabriela"]
LAST = ["Hernandez", "Garcia", "Martinez", "Lopez", "Gonzalez", "Perez", "Rodriguez", "Sanchez", "Ramirez", "Torres",
        "Flores", "Rivera", "Gomez", "Diaz", "Cruz", "Morales", "Ortiz", "Gutierrez", "Chavez", "Ruiz", "Navarro",
        "Castillo", "Jimenez", "Vargas", "Romero", "Mendoza", "Aguilar", "Medina", "Castro", "Reyes"]
BIOS = ["Engineering student, always hungry.", "Coffee lover and weekend cook.", "Looking for the best tacos in GDL.",
        "Vegetarian foodie.", "Spicy food or nothing.", "Sushi on Fridays.", "Brunch enthusiast.",
        "I rate everything I eat.", "Cheap eats near campus.", "Trying every ramen in the city."]
TAG_PHRASES = {
    "spicy": ["really spicy, bring water", "the salsa has a serious kick", "perfect level of heat"],
    "cheap": ["great value for the price", "super cheap and filling", "you eat well for very little money"],
    "big portion": ["huge portion, I could not finish it", "the portion is very generous"],
    "fresh": ["everything tastes very fresh", "super fresh ingredients"],
    "comfort food": ["pure comfort food", "perfect for a rainy day"],
    "for sharing": ["great to share with friends", "order it for the table"],
    "healthy": ["light and healthy", "I felt good after eating it"],
    "breakfast": ["ideal breakfast before class", "best way to start the morning"],
    "vegan": ["the vegan option is actually good", "even my non vegan friends liked it"],
    "cheesy": ["lots of melted cheese", "very cheesy"],
    "local specialty": ["a true tapatio classic", "you cannot leave Guadalajara without trying it"],
    "street food": ["authentic street food vibe", "the kind of place locals go to"],
}
OPENERS = {
    5: ["Amazing {dish}.", "Best {dish} I have had in Guadalajara.", "Loved the {dish}.", "Incredible {dish}, 10/10."],
    4: ["Very good {dish}.", "The {dish} was really tasty.", "Solid {dish}, would order again."],
    3: ["The {dish} was okay.", "Average {dish}, nothing special.", "Decent {dish} but I expected more."],
    2: ["Disappointing {dish}.", "The {dish} was bland.", "Not a fan of the {dish} here."],
    1: ["Terrible {dish}.", "The {dish} was cold and tasteless.", "Would not order the {dish} again."],
}
CLOSERS = {
    5: ["Definitely coming back to {rest}.", "{rest} is now my favorite spot.", "Highly recommended."],
    4: ["{rest} is a good option near {area}.", "Service was friendly.", "Will come back."],
    3: ["Service was slow at {rest}.", "Prices are a bit high for what you get.", "It was fine for a quick meal."],
    2: ["Long wait and a noisy place.", "Too expensive for the quality.", "Probably will not return to {rest}."],
    1: ["Bad service and dirty tables.", "Avoid {rest}.", "Waited 40 minutes for this."],
}
SEARCH_TERMS = ["spicy tacos", "sushi near campus", "cheap breakfast", "vegan food", "ramen", "torta ahogada",
                "pizza with terrace", "seafood aguachile", "coffee to study", "korean bbq", "birria",
                "pet friendly restaurant", "date night italian", "burgers", "dumplings"]
CORE_DESCRIPTIONS = {
    "rest_0001": "Busy street-food taqueria in front of ITESO, famous for al pastor and fast service.",
    "rest_0002": "Small sushi bar with fresh fish and a quiet atmosphere.",
    "rest_0003": "Romantic Italian trattoria with handmade pasta.",
    "rest_0004": "Traditional birrieria with beef birria and consome since 1985.",
    "rest_0005": "Healthy vegetarian place with bowls, vegan tacos and juices.",
}


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def price_level_for(price):
    return 1 if price <= 90 else 2 if price <= 180 else 3 if price <= 300 else 4


def hours_for(rng, cuisine):
    opens = "08:00" if cuisine in ("cafe", "mexican", "healthy") else "13:00"
    closes = rng.choice(["17:00", "22:00", "23:00"]) if cuisine != "cafe" else "21:00"
    days = {d: {"open": opens, "close": closes} for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    if rng.random() < 0.4:
        days[rng.choice(["mon", "sun"])] = {"closed": True}
    return days


def generate(seed=SEED):
    rng = random.Random(seed)
    core = json.loads((config.DATA_DIR / "core_seed.json").read_text(encoding="utf-8"))

    users = core["users"]
    restaurants = core["restaurants"]
    dishes = core["dishes"]
    reviews = core["reviews"]
    lists = core["lists"]
    follows = {u: list(v) for u, v in core["follows"].items()}
    visits = [{"user_id": u, "visited_at": t, "restaurant_id": r} for u, t, r in core["visits"]]
    searches = [{"user_id": u, "searched_at": t, "query_text": q, "filters": f} for u, t, q, f in core["searches"]]
    for r in restaurants:
        r.setdefault("description", CORE_DESCRIPTIONS.get(r["_id"], ""))
        r["address"].setdefault("neighborhood", "ITESO / Periferico Sur" if r["address"]["city"] == "Tlaquepaque" else "Chapalita")
    restaurant_cuisine = {"rest_0001": "mexican", "rest_0002": "japanese", "rest_0003": "italian",
                          "rest_0004": "mexican", "rest_0005": "healthy"}

    # ---------------------------------------------------------------- restaurants + dishes
    used_names = {r["name"] for r in restaurants}
    cuisines = list(CATALOG)
    weights = [10, 5, 7, 6, 6, 6, 4, 4, 6, 2]
    dish_counter = len(dishes)
    for i in range(len(restaurants) + 1, N_RESTAURANTS + 1):
        cuisine = rng.choices(cuisines, weights)[0]
        cat = CATALOG[cuisine]
        for _ in range(50):
            name = "%s %s" % (rng.choice(cat["names"][0]), rng.choice(cat["names"][1]))
            name = name.replace("K- ", "K-")
            if name not in used_names:
                break
        used_names.add(name)
        city, hood, lon, lat = rng.choice(AREAS)
        rid = "rest_%04d" % i
        templates = rng.sample(cat["dishes"], k=min(len(cat["dishes"]), rng.randint(3, 5)))
        factor = rng.choice([0.8, 1.0, 1.0, 1.25, 1.6])
        menu = []
        for t_name, t_desc, t_tags, t_veg, t_price in templates:
            dish_counter += 1
            price = int(round(t_price * factor / 5.0) * 5)
            d = {"_id": "dish_%04d" % dish_counter, "restaurant_id": rid, "restaurant_name": name,
                 "name": t_name, "price": price, "price_level": price_level_for(price),
                 "description": t_desc, "tags": list(t_tags), "vegetarian": t_veg}
            dishes.append(d)
            menu.append(d)
        avg_price = sum(d["price"] for d in menu) / len(menu)
        restaurants.append({
            "_id": rid, "name": name, "cuisine": [cuisine] + cat["extra"],
            "price_level": price_level_for(avg_price),
            "description": rng.choice(cat["ambiance"]),
            "location": {"type": "Point", "coordinates": [round(lon + rng.uniform(-0.012, 0.012), 5),
                                                          round(lat + rng.uniform(-0.012, 0.012), 5)]},
            "address": {"street": "%s %d" % (rng.choice(["Av. Lopez Mateos", "Av. Chapultepec", "Av. Vallarta",
                                                          "Calle Morelos", "Av. Guadalupe", "Av. Patria",
                                                          "Calle Independencia", "Av. Mexico"]), rng.randint(100, 3900)),
                        "neighborhood": hood, "city": city, "state": "Jalisco"},
            "hours": hours_for(rng, cuisine),
            "attributes": {"terrace": rng.random() < 0.45,
                           "vegetarian_options": any(d["vegetarian"] for d in menu),
                           "pet_friendly": rng.random() < 0.3, "delivery": rng.random() < 0.6,
                           "accepts_reservations": rng.random() < 0.4, "wifi": cuisine == "cafe" or rng.random() < 0.3},
            "created_at": iso(datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 80))),
        })
        restaurant_cuisine[rid] = cuisine
    rest_by_id = {r["_id"]: r for r in restaurants}
    quality = {d["_id"]: rng.gauss(0, 0.8) for d in dishes}

    # ---------------------------------------------------------------- users
    used_emails = {u["email"] for u in users}
    for i in range(len(users) + 1, N_USERS + 1):
        first, last = FIRST[(i * 7) % len(FIRST)], rng.choice(LAST)
        email = "%s.%s%d@example.com" % (first.lower(), last.lower(), i)
        used_emails.add(email)
        fav_cuisines = rng.sample(cuisines, k=rng.randint(1, 3))
        dietary = ["vegetarian"] if rng.random() < 0.15 else []
        lo = rng.choice([1, 1, 2])
        users.append({
            "_id": "user_%04d" % i, "email": email, "password_hash": "", "name": "%s %s" % (first, last),
            "city": rng.choice(["Guadalajara", "Zapopan", "Tlaquepaque"]), "bio": rng.choice(BIOS),
            "preferences": {"cuisines": fav_cuisines, "dietary": dietary, "price_range": [lo, rng.choice([2, 3, 4]) if lo == 1 else rng.choice([3, 4])]},
            "favorites": {"restaurants": [], "dishes": []},
            "created_at": iso(datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 45), hours=rng.randint(8, 22))),
        })

    # ---------------------------------------------------------------- reviews + visits
    review_counter = len(reviews)
    taken = {(r["user_id"], r["restaurant_id"], r["dish_id"]) for r in reviews}
    start = datetime(2026, 8, 15, tzinfo=timezone.utc)
    for u in users[3:]:
        prefs = u["preferences"]
        veg = "vegetarian" in prefs["dietary"]
        pool = [d for d in dishes if (d["vegetarian"] or not veg)]
        w = [4.0 if restaurant_cuisine[d["restaurant_id"]] in prefs["cuisines"] else 1.0 for d in pool]
        for d in {id(x): x for x in rng.choices(pool, w, k=rng.randint(10, 24))}.values():
            key = (u["_id"], d["restaurant_id"], d["_id"])
            if key in taken:
                continue
            taken.add(key)
            liked = restaurant_cuisine[d["restaurant_id"]] in prefs["cuisines"]
            score = 3.6 + quality[d["_id"]] + (0.6 if liked else 0) + rng.gauss(0, 0.7)
            rating = max(1, min(5, int(round(score))))
            rest = rest_by_id[d["restaurant_id"]]
            created = start + timedelta(days=rng.randint(0, 96), hours=rng.randint(12, 22), minutes=rng.randint(0, 59))
            phrases = [p for t in d["tags"] if t in TAG_PHRASES for p in [rng.choice(TAG_PHRASES[t])]]
            text = " ".join([rng.choice(OPENERS[rating]).format(dish=d["name"].lower() if rng.random() < 0.5 else d["name"]),
                             (rng.choice(phrases).capitalize() + ".") if phrases and rating >= 3 else "",
                             rng.choice(CLOSERS[rating]).format(rest=rest["name"], area=rest["address"]["neighborhood"])])
            review_counter += 1
            reviews.append({"_id": "rev_%04d" % review_counter, "user_id": u["_id"], "restaurant_id": rest["_id"],
                            "dish_id": d["_id"], "rating": rating, "text": " ".join(text.split()), "created_at": iso(created)})
            visits.append({"user_id": u["_id"], "visited_at": iso(created - timedelta(minutes=rng.randint(30, 90))),
                           "restaurant_id": rest["_id"]})
            if rating >= 5 and rng.random() < 0.5 and d["_id"] not in u["favorites"]["dishes"]:
                u["favorites"]["dishes"].append(d["_id"])
            if rating >= 5 and rng.random() < 0.4 and rest["_id"] not in u["favorites"]["restaurants"]:
                u["favorites"]["restaurants"].append(rest["_id"])
        # a few restaurant-level reviews (no dish)
        for rest in rng.sample(restaurants, k=rng.randint(0, 2)):
            key = (u["_id"], rest["_id"], None)
            if key in taken:
                continue
            taken.add(key)
            rating = max(1, min(5, int(round(3.8 + rng.gauss(0, 0.9)))))
            review_counter += 1
            created = start + timedelta(days=rng.randint(0, 96), hours=rng.randint(12, 22))
            reviews.append({"_id": "rev_%04d" % review_counter, "user_id": u["_id"], "restaurant_id": rest["_id"],
                            "dish_id": None, "rating": rating,
                            "text": "%s %s" % (rest["description"], rng.choice(CLOSERS[rating]).format(
                                rest=rest["name"], area=rest["address"]["neighborhood"])),
                            "created_at": iso(created)})
        # extra visits without a review
        for _ in range(rng.randint(2, 8)):
            visits.append({"user_id": u["_id"], "restaurant_id": rng.choice(restaurants)["_id"],
                           "visited_at": iso(start + timedelta(days=rng.randint(0, 96), hours=rng.randint(8, 22)))})
        for _ in range(rng.randint(2, 7)):
            term = rng.choice(SEARCH_TERMS)
            f = {}
            if rng.random() < 0.4:
                f["price"] = str(rng.choice([1, 2]))
            if rng.random() < 0.2:
                f["terrace"] = "true"
            searches.append({"user_id": u["_id"], "query_text": term, "filters": f,
                             "searched_at": iso(datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 50), hours=rng.randint(8, 23)))})

    # ---------------------------------------------------------------- social graph
    ids = [u["_id"] for u in users]
    by_id = {u["_id"]: u for u in users}
    for u in users[3:]:
        others = [x for x in ids if x != u["_id"]]
        w = [3.0 if set(by_id[x]["preferences"]["cuisines"]) & set(u["preferences"]["cuisines"]) else 1.0 for x in others]
        chosen = {rng.choices(others, w)[0] for _ in range(rng.randint(3, 9))}
        follows[u["_id"]] = sorted(chosen)
    for core_user in ("user_0001", "user_0002", "user_0003"):  # make the core users part of the bigger network
        follows.setdefault(core_user, [])
        for x in rng.sample(ids[3:], 4):
            if x not in follows[core_user]:
                follows[core_user].append(x)
        for x in rng.sample(ids[3:], 5):
            if core_user not in follows[x]:
                follows[x].append(core_user)

    # ---------------------------------------------------------------- lists
    list_counter = len(lists)
    for u in rng.sample(users[3:], 15):
        list_counter += 1
        items = [{"type": "restaurant", "ref_id": r["_id"]} for r in rng.sample(restaurants, 2)] + \
                [{"type": "dish", "ref_id": d["_id"]} for d in rng.sample(dishes, 2)]
        lists.append({"_id": "list_%04d" % list_counter, "user_id": u["_id"],
                      "name": rng.choice(["Want to try", "Creme de la creme", "Cheap eats", "Date night", "Study spots"]),
                      "items": items})

    # ---------------------------------------------------------------- dish views (last 14 days, relative to load day)
    trending = {}
    popular = sorted(dishes, key=lambda d: -quality[d["_id"]])[:45]
    for d in popular:
        city = rest_by_id[d["restaurant_id"]]["address"]["city"]
        base = rng.randint(2, 14)
        trending.setdefault(city, {})[d["_id"]] = [max(0, base + rng.randint(-3, 4)) for _ in range(14)]
    trending.setdefault("Tlaquepaque", {})["dish_0001"] = [rng.randint(18, 26) for _ in range(14)]

    return {
        "generated_with_seed": seed,
        "users": users, "restaurants": restaurants, "dishes": dishes, "reviews": reviews,
        "lists": lists, "follows": follows,
        "visits": sorted(visits, key=lambda v: v["visited_at"]),
        "searches": sorted(searches, key=lambda s: s["searched_at"]),
        "dish_views_days_ago": trending,
        "demo_password": "dishcovery123",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Generate data/dishcovery_data.json")
    p.add_argument("--out", default=str(config.DATA_DIR / "dishcovery_data.json"))
    args = p.parse_args(argv)
    data = generate()
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print("Wrote %s: %d users, %d restaurants, %d dishes, %d reviews, %d visits, %d searches, %d lists, %d follow edges"
          % (args.out, len(data["users"]), len(data["restaurants"]), len(data["dishes"]), len(data["reviews"]),
             len(data["visits"]), len(data["searches"]), len(data["lists"]),
             sum(len(v) for v in data["follows"].values())))


if __name__ == "__main__":
    main()
