"""
Production Website Generator for Demo Websites.
Generates image-rich Tailwind CSS landing pages using Gemini and deploys to Vercel CDN.
Integrated with unified Supabase / Postgres database.
"""
import os
import re
import time
import json
import logging
import urllib.parse
from typing import Dict, Any, Optional, List
import httpx

from database import unified_db, clean_phone_number

logger = logging.getLogger("WebsiteGenerator")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
VERCEL_TOKEN = os.getenv("VERCEL_TOKEN", "")
VERCEL_PROJECT = os.getenv("VERCEL_PROJECT", "demo-websites")

VERIFIED_AVATARS = [
    "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=200&q=80",
    "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=200&q=80",
    "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=200&q=80",
]

NICHE_PALETTES = {
    "dental": {"primary": "cyan-600", "accent": "blue-600", "bg": "bg-slate-50", "badge": "bg-cyan-50 text-cyan-700 border-cyan-200"},
    "doctor": {"primary": "teal-600", "accent": "emerald-600", "bg": "bg-slate-50", "badge": "bg-teal-50 text-teal-700 border-teal-200"},
    "cafe": {"primary": "amber-700", "accent": "orange-600", "bg": "bg-[#FAF7F2]", "badge": "bg-amber-50 text-amber-800 border-amber-200"},
    "bakery": {"primary": "amber-600", "accent": "orange-500", "bg": "bg-[#FDF9F3]", "badge": "bg-amber-50 text-amber-800 border-amber-200"},
    "restaurant": {"primary": "rose-600", "accent": "amber-600", "bg": "bg-stone-50", "badge": "bg-rose-50 text-rose-700 border-rose-200"},
    "salon": {"primary": "rose-600", "accent": "pink-600", "bg": "bg-zinc-50", "badge": "bg-rose-50 text-rose-700 border-rose-200"},
    "gym": {"primary": "emerald-600", "accent": "lime-500", "bg": "bg-slate-950 text-slate-100", "badge": "bg-emerald-950 text-emerald-400 border-emerald-800"},
    "car": {"primary": "blue-600", "accent": "amber-500", "bg": "bg-slate-50", "badge": "bg-blue-50 text-blue-700 border-blue-200"},
    "interior": {"primary": "indigo-600", "accent": "amber-600", "bg": "bg-stone-50", "badge": "bg-indigo-50 text-indigo-700 border-indigo-200"},
}

NICHE_ASSETS = {
    "dental": {
        "hero": "https://images.unsplash.com/photo-1629909613654-28e377c37b09?auto=format&fit=crop&w=1200&q=80",
        "about": "https://images.unsplash.com/photo-1588776814546-1ffcf47267a5?auto=format&fit=crop&w=800&q=80",
        "services": [
            ("Teeth Whitening & Aesthetic Smile", "https://images.unsplash.com/photo-1606811841689-23dfddce3e95?auto=format&fit=crop&w=800&q=80"),
            ("Painless Root Canal & Implants", "https://images.unsplash.com/photo-1588776814546-1ffcf47267a5?auto=format&fit=crop&w=800&q=80"),
            ("Clear Aligners & Orthodontics", "https://images.unsplash.com/photo-1598256989800-fe5f95da9787?auto=format&fit=crop&w=800&q=80"),
            ("Complete Dental Hygiene & Checkups", "https://images.unsplash.com/photo-1609840114035-3c981b782dfe?auto=format&fit=crop&w=800&q=80"),
        ],
    },
    "cafe": {
        "hero": "https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?auto=format&fit=crop&w=1200&q=80",
        "about": "https://images.unsplash.com/photo-1554118811-1e0d58224f24?auto=format&fit=crop&w=800&q=80",
        "services": [
            ("Artisan Espresso & Specialty Coffee", "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?auto=format&fit=crop&w=800&q=80"),
            ("Single Origin Manual Pour Overs", "https://images.unsplash.com/photo-1517256064527-09c73fc73e38?auto=format&fit=crop&w=800&q=80"),
            ("Fresh Butter Croissants & Baked Goods", "https://images.unsplash.com/photo-1555507036-ab1f4038808a?auto=format&fit=crop&w=800&q=80"),
            ("Nitrogen Cold Brews & Craft Tonics", "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?auto=format&fit=crop&w=800&q=80"),
        ],
    },
    "bakery": {
        "hero": "https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=1200&q=80",
        "about": "https://images.unsplash.com/photo-1555507036-ab1f4038808a?auto=format&fit=crop&w=800&q=80",
        "services": [
            ("Artisanal Sourdough & Country Loaves", "https://images.unsplash.com/photo-1549931319-a545dcf3bc73?auto=format&fit=crop&w=800&q=80"),
            ("Custom Celebration & Wedding Cakes", "https://images.unsplash.com/photo-1578985545062-69928b1d9587?auto=format&fit=crop&w=800&q=80"),
            ("French Viennoiserie & Cruffins", "https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=800&q=80"),
            ("Gourmet Fruit Tarts & Macarons", "https://images.unsplash.com/photo-1587314168485-3236d6710814?auto=format&fit=crop&w=800&q=80"),
        ],
    },
    "salon": {
        "hero": "https://images.unsplash.com/photo-1560066984-138dadb4c035?auto=format&fit=crop&w=1200&q=80",
        "about": "https://images.unsplash.com/photo-1521590832167-7bcbfaa6381f?auto=format&fit=crop&w=800&q=80",
        "services": [
            ("Precision Haircut, Balayage & Styling", "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=800&q=80"),
            ("Organic Skin Glow & Hydra Facials", "https://images.unsplash.com/photo-1516975080664-ed2fc6a32937?auto=format&fit=crop&w=800&q=80"),
            ("Gel Manicure, Pedicure & Nail Art", "https://images.unsplash.com/photo-1604654894610-df63bc536371?auto=format&fit=crop&w=800&q=80"),
            ("Bridal Makeovers & Event Glamour", "https://images.unsplash.com/photo-1487412947147-5cebf100ffc2?auto=format&fit=crop&w=800&q=80"),
        ],
    },
    "gym": {
        "hero": "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?auto=format&fit=crop&w=1200&q=80",
        "about": "https://images.unsplash.com/photo-1581009146145-b5ef050c2e1e?auto=format&fit=crop&w=800&q=80",
        "services": [
            ("Heavy Strength & Hypertrophy Training", "https://images.unsplash.com/photo-1581009146145-b5ef050c2e1e?auto=format&fit=crop&w=800&q=80"),
            ("High-Intensity Functional & HIIT Zone", "https://images.unsplash.com/photo-1518611012118-696072aa579a?auto=format&fit=crop&w=800&q=80"),
            ("1-on-1 Elite Personal Coaching", "https://images.unsplash.com/photo-1571019614242-c5c5dee9f50b?auto=format&fit=crop&w=800&q=80"),
            ("Nutrition & Body Composition Protocol", "https://images.unsplash.com/photo-1490645935967-10de6ba17061?auto=format&fit=crop&w=800&q=80"),
        ],
    },
    "restaurant": {
        "hero": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=1200&q=80",
        "about": "https://images.unsplash.com/photo-1550966871-3ed3cdb5ed0c?auto=format&fit=crop&w=800&q=80",
        "services": [
            ("Master Chef's Signature Tasting Menu", "https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=800&q=80"),
            ("Wood-Fired & Authentic Specialties", "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=800&q=80"),
            ("Artisanal Handcrafted Mocktails", "https://images.unsplash.com/photo-1510812431401-41d2bd2722f3?auto=format&fit=crop&w=800&q=80"),
            ("Decadent Desserts & Chef Treats", "https://images.unsplash.com/photo-1551024709-8f23befc6f87?auto=format&fit=crop&w=800&q=80"),
        ],
    },
    "car": {
        "hero": "https://images.unsplash.com/photo-1619642751034-765dfdf7c58e?auto=format&fit=crop&w=1200&q=80",
        "about": "https://images.unsplash.com/photo-1487754180451-c456f719a1fc?auto=format&fit=crop&w=800&q=80",
        "services": [
            ("Computerized Diagnostics & ECU Scan", "https://images.unsplash.com/photo-1486006920555-c77dce18193b?auto=format&fit=crop&w=800&q=80"),
            ("Complete Brake & Suspension Overhaul", "https://images.unsplash.com/photo-1517524008697-84bbe3c3fd98?auto=format&fit=crop&w=800&q=80"),
            ("Premium Ceramic Paint Detailing", "https://images.unsplash.com/photo-1520340356584-f9917d1eea6f?auto=format&fit=crop&w=800&q=80"),
            ("Laser Wheel Alignment & Balancing", "https://images.unsplash.com/photo-1580273916550-e323be2ae537?auto=format&fit=crop&w=800&q=80"),
        ],
    },
    "interior": {
        "hero": "https://images.unsplash.com/photo-1618221195710-dd6b41faaea6?auto=format&fit=crop&w=1200&q=80",
        "about": "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=800&q=80",
        "services": [
            ("Luxury Living Room Architecture", "https://images.unsplash.com/photo-1600566753190-17f0baa2a6c3?auto=format&fit=crop&w=800&q=80"),
            ("Bespoke Modular Kitchen Concepts", "https://images.unsplash.com/photo-1556911220-e15b29be8c8f?auto=format&fit=crop&w=800&q=80"),
            ("Master Bedroom & Walk-in Wardrobes", "https://images.unsplash.com/photo-1616486338812-3dadae4b4ace?auto=format&fit=crop&w=800&q=80"),
            ("Complete Turnkey Home Renovation", "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=800&q=80"),
        ],
    },
}

NICHE_MAPPINGS = [
    (["dent", "teeth", "smile", "orthodont", "doctor", "clinic", "hospital"], "dental"),
    (["bakery", "baker", "pastry", "cake", "bread"], "bakery"),
    (["cafe", "coffee", "espresso", "roast"], "cafe"),
    (["salon", "spa", "beauty", "hair", "parlour", "skin"], "salon"),
    (["gym", "fitness", "crossfit", "workout"], "gym"),
    (["restaurant", "dining", "diner", "food", "bistro"], "restaurant"),
    (["car", "auto", "repair", "mechanic", "garage"], "car"),
    (["interior", "architect", "decor", "furniture"], "interior"),
]

def resolve_category(text: str) -> str:
    t = (text or "").lower()
    for keys, cat in NICHE_MAPPINGS:
        if any(k in t for k in keys):
            return cat
    return "cafe"

def get_niche_assets(niche: str) -> Dict[str, Any]:
    cat = resolve_category(niche)
    return NICHE_ASSETS.get(cat, NICHE_ASSETS["cafe"])

def slugify(text: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[-\s]+", "-", clean).strip("-")
    return slug[:25] or "business"

async def generate_website_html(business: Dict[str, Any]) -> str:
    name = business.get("name", "Local Business")
    niche = business.get("niche", "Services")
    city = business.get("city", "City")
    phone = business.get("phone", "")
    clean_ph = clean_phone_number(phone)
    rating = business.get("rating") or 4.9
    reviews = business.get("reviews") or 48
    address = business.get("address") or f"{city}"

    assets = get_niche_assets(niche)
    s1_title, s1_img = assets["services"][0]
    s2_title, s2_img = assets["services"][1]
    s3_title, s3_img = assets["services"][2]
    s4_title, s4_img = assets["services"][3]

    wa_link = f"https://wa.me/{clean_ph}" if clean_ph else "#"

    system_instruction = """You are a senior front-end engineer and brand designer who builds high-converting websites for local businesses. You output ONE complete, production-ready HTML file and nothing else.

OUTPUT FORMAT
- Raw HTML only. Start with <!DOCTYPE html>, end with </html>. No markdown fences, no commentary.
- Never truncate. No TODOs, no "Lorem ipsum", no placeholder text.
- Tailwind via <script src="https://cdn.tailwindcss.com"></script>, followed by a small inline tailwind.config script defining your brand colors and font families.
- Font Awesome: <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
- Google Fonts: one heading font + one body font that fit the niche, with fallback stacks.

DESIGN DIRECTION (choose a distinct look for the niche, never reuse one template)
- Clinic/dentist: airy, clean, trustworthy. White space, teal or blue accent.
- Salon/spa/beauty: editorial, warm neutrals, elegant serif headings.
- Gym/fitness: dark, high contrast, bold condensed type, one neon accent.
- Restaurant/cafe: warm, rich, photo-led, large imagery.
- Plumber/electrician/auto/repair: confident, bold, strong CTA color, trust-focused.
- Anything else: pick a palette and type pairing that fits the niche.
- Define 1 primary, 1 accent and neutrals. No generic purple-blue gradients, no rows of identical cards.
- Generous spacing, rounded-2xl corners, soft shadows, hover states, scroll-reveal animations (IntersectionObserver), respect prefers-reduced-motion.

IMAGES (none are provided, you choose them)
- Use stock photos that fit the niche and each section: one hero, one about photo, and one per service.
- Primary source: Unsplash CDN URLs in the form https://images.unsplash.com/photo-PHOTOID?auto=format&fit=crop&w=1600&q=80. Use ONLY photo IDs you genuinely know are real and on-topic. Never make up an ID.
- Fallback source: https://loremflickr.com/WIDTH/HEIGHT/keyword1,keyword2?lock=NUMBER, with 1-3 specific keywords for the niche and section (for example dentist,clinic). Use a different lock number for every image so photos differ.
- If you are not sure of a real Unsplash ID, use the fallback URL directly as the src.
- Every <img> has: a descriptive alt, a data-fallback attribute holding its own loremflickr URL, object-cover, and a fixed aspect-ratio container with a brand-colored gradient background.
- Include one small inline script: on the first error of an <img>, swap its src to its data-fallback; on the second error, hide the <img> so the gradient shows through.
- loading="lazy" on everything except the hero.
- Hero: full-bleed image with a dark gradient overlay so text stays readable.
- Testimonial avatars: do not use photos. Use colored circles with the reviewer's initials.

COPY
- Write specific, benefit-led local copy using ONLY the facts provided. Do not invent years in business, awards, certifications, prices, staff names or guarantees.
- Choose 4 services that are typical for the niche and describe each in 1-2 benefit-led sentences.
- H1 includes the niche and city.
- Testimonials: 3 short, believable, non-specific reviews from first name + last initial. Make no claims that can't be verified (no dates, prices or named staff).

SECTIONS (in this order)
1. Sticky nav: name, anchor links, Call button, mobile hamburger (tiny inline JS)
2. Hero: H1, subheadline, rating pill with stars, primary WhatsApp CTA + secondary Call CTA
3. Services: 4 cards with photos
4. About: photo + short story + 3 trust points
5. How it works: 3 steps
6. Testimonials: 3 cards with initials avatars
7. Location & contact: address, tap-to-call, Google Maps iframe (https://maps.google.com/maps?q=URL_ENCODED_ADDRESS&output=embed)
8. Final CTA band
9. Footer
10. Floating WhatsApp button (fixed bottom-right, z-50, subtle pulse, respects safe-area)

TECHNICAL
- Mobile-first, perfect at 375px, no horizontal scroll, tap targets at least 44px.
- Semantic HTML (header/main/section/footer), one h1, meta title + description + viewport + theme-color.
- LocalBusiness JSON-LD.
- Phone uses a tel: link. WhatsApp links use target="_blank" rel="noopener".
- Text contrast at least 4.5:1.

RESPONSIVE RULES (non-negotiable, most visitors will open this on a phone)
- <head> must contain exactly: <meta name="viewport" content="width=device-width, initial-scale=1">
- Load the Tailwind CDN script first, then the tailwind.config script.
- Write every layout mobile-first. Unprefixed Tailwind classes are the mobile layout. Add sm:, md:, lg: only to enhance for larger screens. Never design for desktop first.
- Grids always start as one column (grid-cols-1), then md:grid-cols-2 and lg:grid-cols-4 where appropriate. Any flex row with more than two items is flex-col on mobile and md:flex-row on desktop.
- Never use fixed pixel widths or heights on containers, images or sections (no w-[600px], h-[500px], min-w-[...]). Use w-full, max-w-*, aspect-*, min-h-*.
- Never use w-screen or 100vw. They cause horizontal scroll.
- Wrap every section's content in: mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8
- Fluid type: H1 text-3xl sm:text-4xl lg:text-6xl, H2 text-2xl sm:text-3xl lg:text-4xl, body text-base (never smaller than 16px). Add break-words to headings.
- Hero: no h-screen. Use min-h-[80vh] with py-20, stacked content, and buttons that are w-full sm:w-auto with gap-3.
- Nav: on mobile show only the business name and a hamburger button; the links open in a dropdown panel toggled by tiny inline JS. Desktop links use hidden md:flex, the hamburger uses md:hidden.
- Images: always w-full with object-cover inside an aspect-ratio container, never a fixed width.
- Google Maps iframe: w-full with a fixed height such as h-72, never a fixed width.
- Decorative absolute-positioned elements must sit inside a parent with overflow-hidden so they never extend past the viewport.
- Floating WhatsApp button: fixed bottom-4 right-4, about 56px. Give the footer pb-24 so the button never covers content.
- Tap targets at least 44px, at least 12px between stacked buttons.
- Put overflow-x-hidden on <body> as a safety net only. It does not replace the rules above.
- Before finishing, mentally check the page at 375px, 768px and 1280px: no horizontal scroll, no overlapping elements, no cut-off text."""

    user_prompt = f"""Build the landing page for this business.

- Name: {name}
- Niche: {niche}
- City: {city}
- Rating: {rating}/5 from {reviews}+ Google reviews
- Phone: {phone}
- Address: {address}
- WhatsApp booking link: {wa_link}

Return the full HTML now."""

    api_key = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {
            "parts": [{"text": system_instruction}]
        },
        "contents": [
            {"parts": [{"text": user_prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 8192
        }
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        html = re.sub(r"^```html\s*", "", raw_text.strip(), flags=re.IGNORECASE)
        html = re.sub(r"```$", "", html.strip())
        return html

async def deploy_to_vercel(business_name: str, html_content: str) -> str:
    v_token = os.getenv("VERCEL_TOKEN", VERCEL_TOKEN)
    v_project = os.getenv("VERCEL_PROJECT", VERCEL_PROJECT)

    slug = slugify(business_name)
    deployment_name = f"demo-{slug}-{int(time.time()) % 100000}"

    url = "https://api.vercel.com/v13/deployments?skipAutoDetectionConfirmation=1"
    headers = {
        "Authorization": f"Bearer {v_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "name": deployment_name,
        "project": v_project,
        "files": [{"file": "index.html", "data": html_content}],
        "projectSettings": {"framework": None},
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        data = resp.json()
        domain = data.get("url")
        if not domain and "alias" in data and data["alias"]:
            domain = data["alias"][0]
        return f"https://{domain}" if domain else f"https://{deployment_name}.vercel.app"

def generate_pitch(business: Dict[str, Any], live_url: str) -> str:
    name = business.get("name", "Business")
    niche = business.get("niche", "Services")
    city = business.get("city", "")
    rating = business.get("rating", 4.9)
    reviews = business.get("reviews", 30)

    rev_part = f"⭐ {rating} stars from {reviews}+ customers" if reviews else f"⭐ {rating} stars"
    city_part = f" in {city}" if city else ""

    return (
        f"Hi *{name}* team! 👋\n\n"
        f"I came across your profile on Google Maps with amazing feedback ({rev_part}), but noticed you don't have an official website linked for new clients.\n\n"
        f"When people search for *{niche}{city_part}*, they usually prefer checking services & booking directly on WhatsApp.\n\n"
        f"To show you what's possible, I put together a quick, modern demo website specifically customized for *{name}*:\n"
        f"👉 *{live_url}*\n\n"
        f"Key Highlights:\n"
        f"✅ 100% Mobile Optimized with high-res photography\n"
        f"✅ Direct 1-Click WhatsApp Booking CTA\n"
        f"✅ Showcases your Google reviews & top services\n"
        f"✅ Blazing fast load speed (<1 second)\n\n"
        f"If you like the look and feel, we can link your custom domain within 24 hours. Would you be open to a quick 2-minute chat? No commitment at all!"
    )

async def create_demo_for_business(business: Dict[str, Any], user_id: int = 0) -> Dict[str, Any]:
    name = business.get("name", "Business")
    try:
        html = await generate_website_html(business)
        live_url = await deploy_to_vercel(name, html)
        pitch = generate_pitch(business, live_url)

        # Save to database
        await unified_db.save_site(business, live_url, pitch, user_id)

        # Update leads table if lead ID was attached
        db_id = business.get("id") or business.get("db_id")
        place_id = business.get("place_id")
        if db_id or place_id:
            await unified_db.update_demo_url(db_id or place_id, live_url)

        return {
            "success": True,
            "live_url": live_url,
            "pitch": pitch,
        }
    except Exception as e:
        logger.error(f"Failed to generate demo for {name}: {e}")
        return {"success": False, "error": str(e)}
