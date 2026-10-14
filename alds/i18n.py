import contextlib
import contextvars

LANGS = {"ar": "العربية", "en": "English"}
_current = contextvars.ContextVar("ui_lang", default="en")


def lang() -> str:
    return _current.get()


@contextlib.contextmanager
def use(language):
    token = _current.set(language)
    try:
        yield
    finally:
        _current.reset(token)


def t(text: str, **values) -> str:
    if _current.get() == "ar":
        text = AR.get(text, text)
        values = {k: f"⁨{v}⁩" for k, v in values.items()}
    return text.format(**values) if values else text


AR = {
    "ALDS — LoRA datasets of a character from anime episodes": "ALDS — تجهيز صور LoRA لشخصية من حلقات الأنمي",
    "🟢 The graphics card is used (CUDA)": "🟢 كرت الشاشة يعمل (CUDA)",
    "🔴 Running on the CPU only (slow)": "🔴 يعمل على المعالج فقط (بطيء)",
    "Project (pick one or type a new name)": "المشروع (اختر مشروعًا أو اكتب اسمًا جديدًا)",
    "🔄 Refresh": "🔄 تحديث",
    "Pick a project or type a new project name at the top": "اختر مشروعًا أو اكتب اسم مشروع جديد في الأعلى",
    "Stopped: everything it generated was removed, the project is back as it was.":
        "أُوقفت العملية، وحُذف كل ما ولّدته، فعاد المشروع كما كان قبلها.",
    "⏹ Stopped": "⏹ تم الإيقاف",
    "Error": "خطأ",
    "Warning": "تنبيه",
    "Info": "ملاحظة",
    "⏹ Stop and remove what it made": "⏹ إيقاف وحذف ما وُلّد",
    "⏳ Stopping and undoing...": "⏳ جارٍ الإيقاف والتراجع...",

    "The file or folder doesn't exist": "الملف أو المجلد غير موجود",
    "There are results with this name already. Tick “Replace earlier results” to build it again, or pick another name":
        "توجد نتائج سابقة بهذا الاسم. فعّل «استبدال نتائج سابقة» لإعادة البناء، أو اختر اسمًا آخر",
    "The character wasn't found. Raise “Match threshold” a little or pick other clusters":
        "لم يُعثر على الشخصية. ارفع «حد التطابق» قليلًا أو اختر مجموعات أخرى",
    "No characters were found in the episodes": "لم تُكتشف أي شخصيات في الحلقات",
    "Scan at least one episode first (tab 1)": "امسح حلقة واحدة على الأقل أولًا (التبويب ١)",
    "That cluster number doesn't exist. Numbers change after every scan, refresh the page":
        "رقم مجموعة غير موجود. الأرقام تتغير بعد كل مسح، حدّث الصفحة",
    "There are no images in the uploaded references": "لا توجد صور في المراجع المرفوعة",
    "Not enough clear views to cluster": "لا توجد مشاهد واضحة كافية للتجميع",
    "This project's frames were deleted to save space. To build a new character, scan the episodes in a new project":
        "إطارات هذا المشروع حُذفت لتوفير المساحة. لبناء شخصية جديدة امسح الحلقات في مشروع جديد",
    "The cluster didn't split this strongly, lower “Split strength”": "لم تنقسم المجموعة بهذه الشدة، اخفض «شدة التقسيم»",
    "The cluster is too small to split": "المجموعة أصغر من أن تُقسم",

    "1. Scan episodes": "١. مسح الحلقات",
    "Paste one episode path per line, or the path of a whole folder. "
    "(In Windows Explorer: Shift + right-click the file → Copy as path)":
        "الصق مسار حلقة في كل سطر، أو مسار مجلد كامل. "
        "(في مستكشف ويندوز: Shift + زر الفأرة الأيمن على الملف ← Copy as path)",
    "Episodes": "الحلقات",
    "Find the OP/ED automatically: parts repeated between episodes are left out. With one episode, the next "
    "episode in its folder is used for the comparison":
        "اكتشاف الشارة (OP/ED) تلقائيًا: المقاطع المتكررة بين الحلقات تُستبعد. "
        "مع حلقة واحدة تُستخدم الحلقة المجاورة في المجلد للمقارنة",
    "More times to ignore (optional)": "أوقات إضافية تُتجاهل يدويًا (اختياري)",
    "Advanced settings": "إعدادات متقدمة",
    "You rarely need these: the defaults suit most anime.": "نادرًا ما تحتاج هذه الإعدادات، فالقيم الافتراضية تناسب أغلب الأنمي.",
    "**Opening and ending (OP/ED)**": "**الشارة (OP/ED)**",
    "Shortest OP/ED (seconds)": "أقصر شارة (ثانية)",
    "A part repeated between episodes is left out only if it's at least this long. Lower it if a short OP/ED isn't "
    "found.":
        "يُستبعد المقطع المتكرر بين الحلقات إن كان بهذا الطول أو أطول. اخفضه إن لم تُكتشف شارة قصيرة.",
    "Find the OP/ED again in the scanned episodes": "أعد اكتشاف الشارة في الحلقات الممسوحة",
    "**Which frames are kept** (for new scans)": "**الإطارات المحفوظة** (للمسح القادم)",
    "Time between kept frames (seconds)": "الوقت بين الإطارات المحفوظة (ثانية)",
    "Lower = more frames from each scene. Higher = fewer frames and a faster scan.":
        "أقل = إطارات أكثر من كل مشهد. أعلى = إطارات أقل ومسح أسرع.",
    "Change needed to keep another frame": "التغيّر المطلوب لحفظ إطار آخر",
    "How different a frame must look from the last kept one. Lower = more, more similar frames. Higher = fewer.":
        "كم يجب أن يختلف الإطار عن آخر إطار محفوظ. أقل = إطارات أكثر ومتشابهة أكثر. أعلى = إطارات أقل.",
    "▶ Start scanning": "▶ ابدأ المسح",
    "Episode": "الحلقة",
    "Length (min)": "المدة (دقيقة)",
    "Frames": "إطارات",
    "Left out automatically": "مستبعد تلقائيًا",
    "Episodes scanned in this project": "الحلقات الممسوحة في المشروع",
    "💾 Disk space": "💾 المساحة على القرص",
    "**Safe clean** deletes only what the program will never use again: frames with no character, frames inside the "
    "OP/ED, thumbnails and leftover copies. Nothing you need is lost.":
        "**التنظيف الآمن** يحذف فقط ما لن يستخدمه البرنامج أبدًا: الإطارات التي لا شخصيات فيها، وإطارات الشارة، "
        "والصور المصغّرة، والنسخ الزائدة. لا يضيع شيء تحتاجه.",
    "🧹 Safe clean": "🧹 تنظيف آمن",
    "**Delete all frames** frees the most space and keeps your finished images, but after it this project can't be "
    "built or re-clustered. Do it only when you're done with the project.":
        "**حذف كل الإطارات** يوفّر أكبر مساحة وتبقى صورك النهائية، لكن بعده لا يمكن البناء أو إعادة التجميع في هذا "
        "المشروع. افعله فقط بعد أن تنتهي من المشروع.",
    "I'm done with this project: delete all its frames": "انتهيت من هذا المشروع: احذف كل إطاراته",
    "🗑 Delete all frames": "🗑 حذف كل الإطارات",
    "Log": "السجل",
    "Enter at least one episode path or a folder of episodes": "أدخل مسار حلقة واحدة على الأقل أو مجلد حلقات",
    "The times to skip aren't valid. Example: 0:00-1:55, 21:55-24:30":
        "صيغة أوقات التخطي غير صحيحة. مثال: 0:00-1:55, 21:55-24:30",
    "Starting the scan...": "بدء المسح...",
    "Scan at least one episode first": "امسح حلقة واحدة على الأقل أولًا",
    "Comparing the episodes...": "مقارنة الحلقات...",
    "Select exactly one cluster (the mixed one), then press “Split”": "حدّد مجموعة واحدة فقط (المختلطة) ثم اضغط «قسّم»",
    "Extracted frames": "الإطارات المستخرجة",
    "Scan data": "بيانات المسح",
    "Cluster images": "صور المجموعات",
    "Saved analysis for rebuilds": "التحليل المحفوظ لإعادة البناء",
    "Character {name}": "الشخصية {name}",
    "**Project size: {size}**": "**حجم المشروع: {size}**",
    " — frames deleted, no more builds": " — الإطارات محذوفة، لا يمكن البناء من جديد",
    "| Part | Size |": "| الجزء | الحجم |",
    "Tick the confirmation first: deleting all frames is final and stops any rebuild":
        "فعّل خانة التأكيد أولًا: حذف كل الإطارات نهائي ويمنع إعادة البناء",

    "2. Pick the character": "٢. اختيار الشخصية",
    "Click a character's image to select it, click again to unselect. If the character shows up in more than one "
    "cluster (another outfit, say), pick all of them. **The numbers change after every scan.**":
        "اضغط على صورة الشخصية لتحديدها، واضغط مرة أخرى لإلغاء التحديد. إن ظهرت الشخصية في أكثر من مجموعة "
        "(زي مختلف مثلًا) فاختر كل مجموعاتها. **الأرقام تتغير بعد كل مسح.**",
    "Characters found": "الشخصيات المكتشفة",
    "{id}  ·  {n} views": "{id}  ·  {n} ظهور",
    "Fix the clusters (two characters mixed, or one split up)": "تصحيح المجموعات (شخصيتان مختلطتان، أو شخصية مقسّمة)",
    "**One character in several clusters?** Usually there's nothing to fix: just select all of them.\n\n**Two "
    "characters in one cluster?** Select only that cluster, then split it:":
        "**شخصية في أكثر من مجموعة؟** غالبًا لا يلزم تصحيح شيء: اختر كل مجموعاتها فقط.\n\n"
        "**شخصيتان في مجموعة واحدة؟** اختر تلك المجموعة وحدها، ثم قسّمها:",
    "Split strength": "شدة التقسيم",
    "Lower = more, smaller parts. The other clusters keep their numbers.":
        "أقل = أجزاء أكثر وأصغر. بقية المجموعات تحتفظ بأرقامها.",
    "**Many clusters wrong?** Cluster the whole project again (all the numbers change):":
        "**مجموعات كثيرة خاطئة؟** أعد تجميع المشروع كله (تتغير كل الأرقام):",
    "Cluster size": "حجم المجموعات",
    "Lower = more, smaller clusters, which separates characters that look alike. Higher = fewer, bigger clusters, "
    "which joins a character that got split.":
        "أقل = مجموعات أكثر وأصغر، فتنفصل الشخصيات المتشابهة. أعلى = مجموعات أقل وأكبر، فتجتمع الشخصية المقسّمة.",
    "Hide clusters with fewer views than": "إخفاء المجموعات التي ظهورها أقل من",
    "Small clusters are usually background characters.": "المجموعات الصغيرة غالبًا لشخصيات ثانوية في الخلفية.",
    "Re-cluster the whole project": "أعد تجميع المشروع كله",
    "✂ Split the selected cluster": "✂ قسّم المجموعة المحددة",
    "Selected clusters": "المجموعات المختارة",
    "Cluster preview": "معاينة المجموعة",
    "Or/and: reference images of the character (optional, useful for side characters)":
        "أو/و: صور مرجعية للشخصية (اختياري، مفيد للشخصيات الثانوية)",
    "Trigger word (the character's name)": "كلمة التفعيل (اسم الشخصية)",
    "Anime name as a tag (optional)": "اسم الأنمي كوسم (اختياري)",
    "Enlarge small images with an anime upscaler (CDC): cleaner lines than plain resizing, and small crops "
    "become usable":
        "تكبير الصور الصغيرة بنموذج مخصص للأنمي (CDC): خطوط أوضح من التكبير العادي، ويُنقذ القصّات الصغيرة",
    "Enlarge every image smaller than this to it (pixels; use your training resolution)":
        "كبّر كل صورة أصغر من هذا الحجم إليه (بكسل؛ اجعله بدقة التدريب)",
    "The defaults suit most anime. If the result isn't right, change one setting and build again: rebuilding is "
    "fast.":
        "القيم الافتراضية تناسب أغلب الأنمي. إن لم تعجبك النتيجة فغيّر إعدادًا واحدًا وابنِ من جديد، فإعادة البناء "
        "سريعة.",
    "Match threshold": "حد التطابق",
    "Lower = only clear matches, fewer images. Higher = more images, but other characters may slip in.":
        "أقل = الصور المؤكدة فقط وعدد أقل. أعلى = صور أكثر، لكن قد تدخل شخصيات أخرى.",
    "Duplicate removal": "إزالة التكرار",
    "Lower = removes more look-alike images. Higher = keeps more similar ones.":
        "أقل = يحذف صورًا متشابهة أكثر. أعلى = يُبقي صورًا متشابهة أكثر.",
    "Smallest image size (pixels)": "أصغر حجم للصورة (بكسل)",
    "Smaller crops are left out. Turning on enlarging lowers it to 320.":
        "القصّات الأصغر تُستبعد. تفعيل التكبير يخفضه إلى 320.",
    "Follow the character within a shot": "تتبّع الشخصية داخل اللقطة",
    "1 = off (recommended). Higher takes more frames from the same shot, but may let other characters in.":
        "1 = متوقف (يُنصح به). أعلى = إطارات أكثر من اللقطة نفسها، لكن قد تدخل شخصيات أخرى.",
    "Tagging model": "نموذج الوسوم",
    "EVA02_Large is the most accurate; the others are faster.": "EVA02_Large الأدق، والبقية أسرع.",
    "Options": "خيارات",
    "Leave out other characters, using the clusters you didn't pick":
        "استبعاد الشخصيات الأخرى اعتمادًا على المجموعات التي لم تخترها",
    "Separate outfits automatically (a tag per outfit after the trigger word)":
        "فصل الأزياء تلقائيًا (وسم لكل زي بعد كلمة التفعيل)",
    "Put anime screencap at the start of every caption": "وسم anime screencap في أول كل وصف",
    "Keep hair and eye tags in the captions": "إبقاء صفات الشعر والعيون في الوصف",
    "Keep images with text on screen": "إبقاء الصور التي فيها نصوص",
    "Keep images crowded with other characters": "إبقاء الصور المزدحمة بشخصيات أخرى",
    "Keep chibi and blurry drawings": "إبقاء الرسم المصغّر (chibi) والضبابي",
    "Keep black-and-white and sepia images (flashbacks)": "إبقاء الصور بالأبيض والأسود والبني (مشاهد الذكريات)",
    "Save the left-out images in a {folder} folder": "حفظ الصور المستبعدة في مجلد {folder}",
    "Analyse from scratch, ignore the saved analysis (much slower, rarely needed)":
        "إعادة التحليل من الصفر وتجاهل المحفوظ (أبطأ بكثير، نادرًا ما تحتاجه)",
    "Replace earlier results with the same name (clears your earlier review)":
        "استبدال نتائج سابقة بنفس الاسم (يمسح مراجعتك السابقة)",
    "▶ Build the image set": "▶ ابنِ مجموعة الصور",
    "Report": "التقرير",
    "Type the trigger word (the character's name)": "اكتب كلمة التفعيل (اسم الشخصية)",
    "Pick at least one cluster of images, or upload reference images":
        "اختر مجموعة واحدة على الأقل من الصور، أو ارفع صورًا مرجعية",
    "Starting the build...": "بدء البناء...",

    "Close-up": "لقطة قريبة",
    "Upper body": "نصف علوي",
    "Cowboy shot": "حتى الفخذ",
    "Full body": "جسم كامل",
    "Front": "أمام",
    "Three-quarter": "ثلاثة أرباع",
    "Side": "جانب",
    "Back": "خلف",
    "From above": "من الأعلى",
    "From below": "من الأسفل",
    "Whole character": "الشخصية كاملة",
    "Head": "الرأس",

    "3. Review": "٣. المراجعة",
    "Remove every image that isn't the character, starting with the ones marked ⚠. **N** (not this character): "
    "an image of another character - the program learns from it, marks what looks like it with 🚫 and leaves it "
    "out of every later build. **Delete**: a bad image of the character itself; nothing is learned. "
    "**← →** to move, **Ctrl+Z** to undo.":
        "أزل كل صورة ليست للشخصية، وابدأ بالصور المعلّمة ⚠. "
        "**N** (ليست الشخصية): لصورة شخصية أخرى، فيتعلّم منها البرنامج: يعلّم ما يشبهها بـ🚫 "
        "ويستبعده في كل بناء قادم. **Delete**: لصورة سيئة للشخصية نفسها، ولا يتعلّم منها شيئًا. "
        "**← →** للتنقل، و**Ctrl+Z** للتراجع.",
    "Character": "الشخصية",
    "Show": "عرض",
    "All": "الكل",
    "All ({n})": "الكل ({n})",
    "⚠ To check ({n})": "⚠ للمراجعة ({n})",
    "🚫 Like what you rejected ({n})": "🚫 تشبه ما رفضته ({n})",
    "🧥 Outfit {id}: {tags} ({n})": "🧥 زي {id}: {tags} ({n})",
    "{shot} · {angle} ({n})": "{shot} · {angle} ({n})",
    "{shot} · {angle}": "{shot} · {angle}",
    "No images here.": "لا توجد صور هنا.",
    "**{i} / {n}** — {shot} · {angle}": "**{i} / {n}** — {shot} · {angle}",
    " — ⚠ needs a check": " — ⚠ تحتاج تأكيدًا",
    " — 🚫 looks like an image you rejected as another character": " — 🚫 تشبه صورة رفضتها كشخصية أخرى",
    "Crop: {crop} — episode {ep} at {at} — match score {score} (lower is better) — sharpness {sharp}":
        "القص: {crop} — الحلقة {ep} عند {at} — درجة التطابق {score} (الأقل أفضل) — الحدة {sharp}",
    " — upscaled ×{f}": " — مُكبّرة ×{f}",
    "Pick a character.": "اختر شخصية.",
    "**{n}** images — **{r}** to check — deleted: {d}": "**{n}** صورة — منها **{r}** للمراجعة — المحذوفة: {d}",
    " — rejected as another character: {n}": " — رُفضت كشخصية أخرى: {n}",
    "← Previous": "→ السابق",
    "Next →": "التالي ←",
    "🚫 Not this character (N)": "🚫 ليست الشخصية (N)",
    "🗑 Bad image (Delete)": "🗑 صورة سيئة (Delete)",
    "↶ Undo": "↶ تراجع",
    "Caption": "الوصف (caption)",
    "💾 Save caption": "💾 حفظ الوصف",
    "Wrong group? Move it to": "تصنيف خاطئ؟ انقلها إلى",
    "↪ Move": "↪ نقل",
    "Forget all images rejected as another character": "نسيان كل الصور المرفوضة كشخصية أخرى",
    "No image selected": "لا توجد صورة محددة",
    "This character was built by an older version of the program: build it again once so it can learn from "
    "rejections. Or remove the image with “Bad image”.":
        "هذه الشخصية بُنيت بإصدار أقدم من البرنامج: أعد بناءها مرة واحدة ليتعلّم من الرفض. "
        "أو احذف الصورة بزر «صورة سيئة».",
    "Rejected as another character. {n} remaining images look like it: pick “🚫 Like what you rejected” under "
    "“Show”.":
        "رُفضت كشخصية أخرى. {n} صورة باقية تشبه ما رفضته: اخترها من «🚫 تشبه ما رفضته» في قائمة العرض.",
    "Rejected as another character; every later build leaves out what looks like it.":
        "رُفضت كشخصية أخرى، وسيستبعد البرنامج ما يشبهها في كل بناء قادم.",
    "Nothing to undo": "لا يوجد حذف للتراجع عنه",
    "Pick a character": "اختر شخصية",
    "The program forgot {n} rejected images. The images themselves stay deleted.":
        "نسي البرنامج {n} صورة مرفوضة. الصور نفسها تبقى في المحذوفات.",
    "Pick an image and the target group": "اختر صورة والمجلد المطلوب",
    "Caption saved": "تم حفظ الوصف",

    "4. Tags": "٤. الوسوم",
    "All tags in the character's captions and how often they appear. Click a tag in the table to select it, then "
    "remove or replace it in **all** captions at once. Every change can be undone.":
        "كل الوسوم في أوصاف الشخصية وعدد مرات ظهورها. اضغط على وسم في الجدول لتحديده، "
        "ثم احذفه أو استبدله في **كل** الأوصاف دفعة واحدة. كل تعديل يمكن التراجع عنه.",
    "Search": "بحث",
    "Tag": "الوسم",
    "Count": "العدد",
    "Selected tags": "الوسوم المحددة",
    "🗑 Remove the selected from all captions": "🗑 احذف المحدد من كل الأوصاف",
    "Replace the selected with (empty = remove)": "استبدل المحدد بـ (فارغ = حذف)",
    "↔ Replace": "↔ استبدل",
    "Add a tag to every caption": "أضف وسمًا لكل الأوصاف",
    "➕ Add": "➕ أضف",
    "↶ Undo the last change (Ctrl+Z)": "↶ تراجع عن آخر تعديل (Ctrl+Z)",
    "**Outfits:** after deleting images in review, separate the outfits again to update them.":
        "**الأزياء:** بعد حذف صور في المراجعة أعد فصل الأزياء ليُحدَّث توزيعها.",
    "🧥 Separate the outfits again": "🧥 أعد فصل الأزياء",
    "Pick a built character.": "اختر شخصية مبنية.",
    "**{n}** captions — **{k}** different tags — changes you can undo: {u}":
        "**{n}** وصف — **{k}** وسم مختلف — تعديلات قابلة للتراجع: {u}",
    "Pick the character": "اختر الشخصية",
    "Changed {n} captions": "عُدّل {n} وصف",
    "Pick one or more tags in the table": "اختر وسمًا أو أكثر من الجدول",
    "Type the tag to add": "اكتب الوسم المراد إضافته",
    "No change to undo": "لا يوجد تعديل للتراجع عنه",
    "Restored {n} captions": "استُرجع {n} وصف",

    "5. Save the result": "٥. حفظ الناتج",
    "Saves the reviewed images with their captions in a folder named after the character, inside the place you "
    "choose. That folder is the dataset you train on.":
        "يحفظ الصور بعد المراجعة مع ملفات الوصف في مجلد باسم الشخصية داخل المكان الذي تختاره. "
        "هذا المجلد هو مجموعة البيانات التي تدرّب عليها.",
    "Save to (paste a folder path; a folder named after the character is made in it)":
        "مكان الحفظ (الصق مسار مجلد؛ يُنشأ فيه مجلد باسم الشخصية)",
    "💾 Save the images and captions": "💾 احفظ الصور والأوصاف",
    "Shot": "اللقطة",
    "Angle": "الزاوية",
    "Distribution": "التوزيع",
    "🗑 Delete the project from the program folder (after saving)": "🗑 حذف المشروع من مجلد البرنامج (بعد الحفظ)",
    "I understand deleting the project is final and can't be undone": "أفهم أن حذف المشروع نهائي ولا يمكن التراجع عنه",
    "🗑 Delete the project": "🗑 احذف المشروع",
    "Type or paste the path of the place to save in": "اكتب أو الصق مسار المكان الذي تريد الحفظ فيه",
    "Type the full path, such as {example}": "اكتب المسار كاملًا، مثل {example}",
    "Pick a place outside the program's projects folder, or the images would be deleted with the project":
        "اختر مكانًا خارج مجلد مشاريع البرنامج، وإلا حُذفت الصور مع المشروع",
    "There are no images for this character. Build it first (tab 2).": "لا توجد صور لهذه الشخصية. ابنِها أولًا (التبويب ٢).",
    "**{n} images** will be saved with {c} caption files.": "**سيُحفظ {n} صورة** مع {c} ملف وصف (caption).",
    "- Trigger word: `{name}`": "- كلمة التفعيل: `{name}`",
    " — anime name: `{series}`": " — اسم الأنمي: `{series}`",
    "- Upscaled with the anime model: {n}": "- مُكبّرة بنموذج الأنمي: {n}",
    "- Outfit {id} `{token}`: {n} images ({tags})": "- زي {id} `{token}`: {n} صورة ({tags})",
    "- ⚠ **{n} images are still marked to check**, and will be saved with the rest. Check them in tab 3 first.":
        "- ⚠ **{n} صورة ما زالت معلّمة للمراجعة**، وستُحفظ معها. راجعها أولًا في التبويب ٣.",
    "- 🚫 **{n} images look like one you rejected as another character**. Check them in tab 3.":
        "- 🚫 **{n} صورة تشبه صورة رفضتها كشخصية أخرى**. راجعها في التبويب ٣.",
    "- ⚠ {n} images have no caption file.": "- ⚠ {n} صورة بلا ملف وصف.",
    "**Saving to:** `{path}`": "**مكان الحفظ:** `{path}`",
    "Total": "المجموع",
    "There is a folder named {name} in that place that the program didn't make, so it won't be overwritten. "
    "Pick another place.":
        "يوجد مجلد بالاسم {name} في هذا المكان ولم يُنشئه البرنامج، فلن يُكتب فوقه. اختر مكانًا آخر.",
    "Deletes the whole project folder **{name}** from the program folder ({size}): frames, characters and saved "
    "analysis. The original episodes and the images you saved elsewhere aren't touched.":
        "يحذف مجلد المشروع **{name}** كله من مجلد البرنامج ({size}): الإطارات والشخصيات والتحليل المحفوظ. "
        "الحلقات الأصلية والصور التي حفظتها في مكان آخر لا تُمس.",
    "Saved from it: ": "حُفظ منه: ",
    "`{char}` → `{path}`": "`{char}` ← `{path}`",
    ", ": "، ",
    "⚠ **No character of this project was saved yet.**": "⚠ **لم تحفظ أي شخصية من هذا المشروع بعد.**",
    "The project doesn't exist": "المشروع غير موجود",
    "Tick the confirmation first: deleting the project is final": "فعّل خانة التأكيد أولًا: حذف المشروع نهائي",
    "Some files couldn't be deleted (open in another program?): {error}":
        "تعذّر حذف بعض الملفات (ربما مفتوحة في برنامج آخر): {error}",
    "Deleted the project {name} and freed {size}.": "حُذف المشروع {name} وتحرّرت {size}.",
}
