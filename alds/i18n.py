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
    "Settings or identity feedback changed. Run the preview again to see the updated result.":
        "تغيّرت الإعدادات أو مراجعة الهوية. شغّل المعاينة مجددًا لعرض النتيجة المحدّثة.",
    "✅ Definitely this character": "✅ هذه الشخصية بالتأكيد",
    "✅ Identity references and feedback preview": "✅ مراجع الهوية ومعاينة أثر المراجعة",
    "Confirm clear examples, especially different angles and outfits. Ambiguous images appear first in All.":
        "أكّد الصور الواضحة، خاصة الزوايا والملابس المختلفة. تظهر صور الهوية الملتبسة أولًا عند اختيار «الكل».",
    "Confirmed references": "المراجع المؤكدة",
    "↶ Remove this confirmation": "↶ إلغاء هذا التأكيد",
    "🔎 Preview confirmation and rejection effects": "🔎 معاينة أثر التأكيد والرفض",
    "Changed matches (when source frames are available)": "المطابقات المتغيرة (عند توفر الإطارات الأصلية)",
    "Uses the last build's references and settings to compare identity matching without manual feedback "
    "against all current confirmations and rejections. Counts are frames, before the scene and "
    "quality filters and deduplication. Deleted images stay deleted. Restore missing frames before rebuilding.":
        "تستخدم مراجع وإعدادات آخر بناء لمقارنة مطابقة الهوية دون مراجعة يدوية بنتيجتها مع جميع التأكيدات والرفض الحالية. "
        "الأعداد للإطارات قبل فلاتر المشاهد والجودة وإزالة التكرار. تبقى الصور المحذوفة محذوفة. استعد الإطارات المفقودة قبل إعادة البناء.",
    "Run the feedback preview after changing confirmations or rejections.": "شغّل معاينة الأثر بعد تغيير التأكيدات أو الرفض.",
    "Matched frames: {before} → {after}. New: {added}; excluded: {removed}; different person: {switched}.":
        "الإطارات المطابقة: {before} ← {after}. جديدة: {added}؛ مستبعدة: {removed}؛ تغيّر الشخص المختار: {switched}.",
    "References: {confirmed} confirmed, {rejected} rejected. Showing up to 24 changed frames.":
        "المراجع: {confirmed} مؤكدة و{rejected} مرفوضة. تُعرض تفاصيل ٢٤ إطارًا متغيرًا كحد أقصى.",
    "Current identity distance: {score}. This is a distance, not a confidence percentage.":
        "مسافة الهوية الحالية: {score}. هذا مقياس اختلاف، وليس نسبة ثقة.",
    "✅ You confirmed this character.": "✅ أكّدتَ هوية هذه الشخصية.",
    "❓ Check identity: weak match or close to another character.": "❓ راجع الهوية: المطابقة ضعيفة أو قريبة من شخصية أخرى.",
    "Start with ❓ ambiguous identities and ⚠ images to check. Confirm clear examples with "
    "**Definitely this character**. **N** rejects another character; **Delete** removes a bad "
    "image without learning its identity. **← →** to move, **Ctrl+Z** to undo removal. "
    "Manage confirmations and preview their effect in **Identity references and feedback preview**.":
        "ابدأ بالهويات الملتبسة ❓ والصور المعلّمة للمراجعة ⚠. أكّد الصور الواضحة بزر **هذه الشخصية بالتأكيد**. "
        "**N** لرفض شخصية أخرى، و**Delete** لحذف صورة سيئة دون تعلم هويتها. **← →** للتنقل، و**Ctrl+Z** للتراجع عن الحذف. "
        "أدر التأكيدات وعاين أثرها من **مراجع الهوية ومعاينة أثر المراجعة**.",
    "Margin to another character: {margin} (larger is clearer).": "الفارق عن شخصية أخرى: {margin} (الأكبر أوضح).",
    " — confirmed references: {n}": " — المراجع المؤكدة: {n}",
    "❓ Ambiguous identity ({n})": "❓ هوية ملتبسة ({n})",
    "✅ Confirmed identity ({n})": "✅ هوية مؤكدة ({n})",
    "Saved as an identity reference. Preview the effect before rebuilding.": "حُفظت الصورة كمرجع للهوية. عاين الأثر قبل إعادة البناء.",
    "Build this character once to save its identity features.": "أعد بناء هذه الشخصية مرة واحدة لحفظ خصائص هويتها.",
    "Scan the episodes before previewing identity feedback.": "افحص الحلقات قبل معاينة أثر مراجعة الهوية.",
    "Pick a confirmed reference.": "اختر مرجعًا مؤكدًا.",
    "Change": "التغيّر",
    "Time": "الوقت",
    "Before distance": "المسافة قبل",
    "After distance": "المسافة بعد",
    "Before": "قبل",
    "After": "بعد",
    "new match": "مطابقة جديدة",
    "no longer matched": "لم يعد مطابقًا",
    "different person": "تغيّر الشخص المختار",
    "There are results with this name already. Enable rebuilding to save a version and build again, or pick another name.":
        "توجد نتائج سابقة بهذا الاسم. فعّل إعادة البناء لحفظ نسخة والبناء مجددًا، أو اختر اسمًا آخر.",
    "Restore this project's frames in tab 1 before building again.": "استعد إطارات المشروع من التبويب ١ قبل إعادة البناء.",
    "Build previews": "معاينات البناء",
    " — restore frames before building again": " — استعد الإطارات قبل إعادة البناء",
    "Confirm deleting the frames. The original episodes are needed to restore them.":
        "أكّد حذف الإطارات. ستحتاج الحلقات الأصلية لاستعادتها.",
    "**Delete all frames** keeps your finished images and saved versions. Restore the frames from the original episodes before building again.":
        "**حذف جميع الإطارات** يحتفظ بالصور النهائية والنسخ المحفوظة. استعد الإطارات من الحلقات الأصلية قبل إعادة البناء.",
    "Delete extracted frames; keep finished images and versions": "احذف الإطارات المستخرجة واحتفظ بالصور النهائية والنسخ",
    "**Restore frames:** recover missing frames using the original episodes. Character groups and reviewed images stay as they are.":
        "**استعادة الإطارات:** استرجع الإطارات المفقودة من الحلقات الأصلية. تبقى مجموعات الشخصيات والصور المراجعة كما هي.",
    "Episodes folder if moved (optional)": "مجلد الحلقات إن نُقلت (اختياري)",
    "↶ Restore missing frames": "↶ استعد الإطارات المفقودة",
    "Rebuild this character: save a version and keep matching reviews": "أعد بناء الشخصية مع حفظ نسخة ونقل مراجعات الصور المطابقة",
    "🔎 Preview these settings": "🔎 عاين هذه الإعدادات",
    "🔎 Settings preview": "🔎 معاينة الإعدادات",
    "Preview 12 frames before building. Your finished images stay as they are.":
        "عاين ١٢ إطارًا قبل البناء. تبقى صورك النهائية كما هي.",
    "Accepted and excluded scenes": "المشاهد المقبولة والمستبعدة",
    "{frames} sampled frames · {accepted} accepted scenes. Duplicates are checked within this sample. Upscaling and outfit tags are applied in the full build.":
        "عينة من {frames} إطارًا · {accepted} مشهدًا مقبولًا. تُقارن المشاهد المكررة داخل العينة. التكبير ووسوم الأزياء يُطبّقان عند البناء الكامل.",
    "🕘 Saved build versions": "🕘 نسخ البناء المحفوظة",
    "A version is saved before every rebuild. Restoring also saves the current result. Versions stay inside this project; images that didn't change are stored only once.":
        "تُحفظ نسخة قبل كل إعادة بناء، وقبل استعادة نسخة أيضًا. تبقى النسخ داخل المشروع، والصور التي لم تتغير تُخزَّن مرة واحدة فقط.",
    "Saved version": "النسخة المحفوظة",
    "💾 Save current version": "💾 احفظ النسخة الحالية",
    "↶ Restore selected version": "↶ استعد النسخة المختارة",
    "No saved version selected.": "لم تُختر نسخة محفوظة.",
    "Delete the selected version for good": "احذف النسخة المختارة نهائيًا",
    "🗑 Delete version": "🗑 احذف النسخة",
    "Tick the confirmation first: a deleted version can't be restored.":
        "فعّل خانة التأكيد أولًا: النسخة المحذوفة لا يمكن استعادتها.",
    "Deleted version {id}.": "حُذفت النسخة {id}.",
    "This character is being rebuilt, restored or saved. Try again when it finishes.":
        "يجري الآن بناء هذه الشخصية أو استعادتها أو حفظها. حاول مجددًا عندما ينتهي.",
    "{date} · {n} images · {reason}": "{date} · {n} صورة · {reason}",
    "manual": "حفظ يدوي",
    "before rebuild": "قبل إعادة البناء",
    "before restore": "قبل الاستعادة",
    "Saved: {saved} images · Current: {current}\n\nCurrent result: {added} added, {removed} removed, {captions} captions changed, {moved} moved to another group.":
        "المحفوظة: {saved} صورة · الحالية: {current}\n\nفي النتيجة الحالية: {added} مضافة، {removed} محذوفة، {captions} أوصاف معدّلة، {moved} منقولة لمجموعة أخرى.",
    "Changed build settings (saved → current):": "إعدادات البناء المتغيّرة (المحفوظة ← الحالية):",
    "accepted": "مقبولة",
    "identity threshold": "خارج حد تطابق الشخصية",
    "looks like another character": "تشبه شخصية أخرى",
    "character too small in the scene": "الشخصية صغيرة جدًا في المشهد",
    "another character in the scene": "شخصية أخرى في المشهد",
    "dark or faded": "مظلمة أو باهتة",
    "text on screen": "كتابة على الصورة",
    "chibi or blurry": "رسم تشيبي أو ضبابي",
    "black and white or sepia": "أبيض وأسود أو سيبيا",
    "near-duplicate": "شبه مكررة",
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
    "The character wasn't found. Raise “Match threshold” a little or pick other clusters":
        "لم يُعثر على الشخصية. ارفع «حد التطابق» قليلًا أو اختر مجموعات أخرى",
    "No characters were found in the episodes": "لم تُكتشف أي شخصيات في الحلقات",
    "Scan at least one episode first (tab 1)": "امسح حلقة واحدة على الأقل أولًا (التبويب ١)",
    "That cluster number doesn't exist. Numbers change after every scan, refresh the page":
        "رقم مجموعة غير موجود. الأرقام تتغير بعد كل مسح، حدّث الصفحة",
    "There are no images in the uploaded references": "لا توجد صور في المراجع المرفوعة",
    "Not enough clear views to cluster": "لا توجد مشاهد واضحة كافية للتجميع",
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
    "⚙️ Advanced settings": "⚙️ إعدادات متقدمة",
    "You rarely need these: the defaults suit most anime.": "نادرًا ما تحتاج هذه الإعدادات، فالقيم الافتراضية تناسب أغلب الأنمي.",
    "**Opening and ending (OP/ED)**": "**الشارة (OP/ED)**",
    "Shortest OP/ED (seconds)": "أقصر شارة (ثانية)",
    "A part repeated between episodes is left out only if it's at least this long. Lower it if a short OP/ED isn't "
    "found.":
        "يُستبعد المقطع المتكرر بين الحلقات إن كان بهذا الطول أو أطول. اخفضه إن لم تُكتشف شارة قصيرة.",
    "🔁 Find the OP/ED again in the scanned episodes": "🔁 أعد اكتشاف الشارة في الحلقات الممسوحة",
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
    "💽 Disk space": "💽 المساحة على القرص",
    "**Safe clean** deletes only what the program will never use again: frames with no character, frames inside the "
    "OP/ED, thumbnails and leftover copies. Nothing you need is lost.":
        "**التنظيف الآمن** يحذف فقط ما لن يستخدمه البرنامج أبدًا: الإطارات التي لا شخصيات فيها، وإطارات الشارة، "
        "والصور المصغّرة، والنسخ الزائدة. لا يضيع شيء تحتاجه.",
    "🧹 Safe clean": "🧹 تنظيف آمن",
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
    "| Part | Size |": "| الجزء | الحجم |",

    "2. Pick the character": "٢. اختيار الشخصية",
    "Click a character's image to select it, click again to unselect. If the character shows up in more than one "
    "cluster (another outfit, say), pick all of them. **The numbers change after every scan.**":
        "اضغط على صورة الشخصية لتحديدها، واضغط مرة أخرى لإلغاء التحديد. إن ظهرت الشخصية في أكثر من مجموعة "
        "(زي مختلف مثلًا) فاختر كل مجموعاتها. **الأرقام تتغير بعد كل مسح.**",
    "Characters found": "الشخصيات المكتشفة",
    "{id}  ·  {n} views": "{id}  ·  {n} ظهور",
    "🧩 Fix the clusters (two characters mixed, or one split up)": "🧩 تصحيح المجموعات (شخصيتان مختلطتان، أو شخصية مقسّمة)",
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
    "🔁 Re-cluster the whole project": "🔁 أعد تجميع المشروع كله",
    "✂ Split the selected cluster": "✂ قسّم المجموعة المحددة",
    "Selected clusters": "المجموعات المختارة",
    "Cluster preview": "معاينة المجموعة",
    "Or/and: reference images of the character (optional, useful for side characters)":
        "أو/و: صور مرجعية للشخصية (اختياري، مفيد للشخصيات الثانوية)",
    "Trigger word (the character's name)": "كلمة التفعيل (اسم الشخصية)",
    "Anime name as a tag (optional)": "اسم الأنمي كوسم (اختياري)",
    "Enlarge small scenes with an anime upscaler: cleaner lines than plain resizing":
        "تكبير المشاهد الصغيرة بموديل مخصص للأنمي: خطوط أوضح من التكبير العادي",
    "Upscaling model": "موديل التكبير",
    "Model version": "نسخة الموديل",
    "Automatic (recommended)": "تلقائي (يُنصح به)",
    'Automatic uses 2x for enlargements up to double and 4x above. Choosing one version downloads only that version.':
        "يستخدم «تلقائي» نسخة 2x للتكبير حتى الضعف و4x لما فوقه. واختيار نسخة واحدة يحمّل هذه النسخة فقط.",
    "Press ! next to a model to read about it.": "اضغط ! بجانب أي موديل لتقرأ عنه.",
    "🗑 Delete this model to free space": "🗑 احذف هذا الموديل لتوفير المساحة",
    "✅ {name} is downloaded ({size} MB).": "✅ {name} محمَّل ({size} MB).",
    "⬇ {name} isn't downloaded yet ({size} MB). It's downloaded when you choose it.":
        "⬇ {name} غير محمَّل بعد ({size} MB). يُحمَّل عند اختياره.",
    "Downloading {name}...": "جارٍ تحميل {name}...",
    "Couldn't download {name}. Check the internet connection and try again.":
        "تعذّر تحميل {name}. تحقق من الاتصال بالإنترنت وحاول مجددًا.",
    "Deleted {name} and freed {size} MB. It's downloaded again when you choose it.":
        "حُذف {name} وتحرّرت {size} MB. يُحمَّل من جديد عند اختياره.",
    "Pick a model": "اختر موديلًا",
    'waifu2x (swin_unet, art) by nagadomi, the ONNX version published by deepghs. It enlarges without redrawing: it removes compression noise and sharpens the least, so the scene looks like the original. Recommended. Two versions, 2x (17 MB) and 4x (19 MB); Automatic uses 2x for enlargements up to double and 4x above. License: MIT.':
        'waifu2x (swin_unet، نسخة الرسوم) من nagadomi، بنسخة ONNX التي نشرتها deepghs. يكبّر الصورة دون أن يعيد رسمها: يزيل تشويش الضغط ويضيف أقل قدر من الحدة، فيبقى المشهد شبيهًا بالأصل. هو الموصى به. له نسختان، 2x (17 MB) و4x (19 MB)؛ والخيار «تلقائي» يستخدم 2x للتكبير حتى الضعف و4x لما فوقه. الترخيص: MIT.',
    'Real-ESRGAN animevideov3 by Tencent ARC, made for anime video; ONNX conversion from Hugging Face (the original is a PyTorch file). Cleaner, slightly crisper lines than waifu2x and the fastest. 4x only, 2.5 MB to download. License: BSD-3-Clause.':
        'Real-ESRGAN animevideov3 من Tencent ARC، مصمم لفيديو الأنمي؛ نسخة ONNX محوّلة من Hugging Face (الأصل ملف PyTorch). خطوطه أنظف وأوضح قليلًا من waifu2x، وهو الأسرع. نسخة 4x فقط، والتحميل 2.5 MB. الترخيص: BSD-3-Clause.',
    "AnimeSharp by Kim2091, from the author's own page. It sharpens lines strongly, which can look too sharp on soft anime. Two versions, 2x (V3, 34 MB) and 4x (34 MB); Automatic uses 2x for enlargements up to double and 4x above. License: CC BY-NC-SA 4.0, non-commercial use only.":
        'AnimeSharp من Kim2091، من صفحة المؤلف نفسه. يزيد حدة الخطوط كثيرًا، وقد تبدو حادة أكثر من اللازم في الأنمي الناعم. له نسختان، 2x (V3، 34 MB) و4x (34 MB)؛ والخيار «تلقائي» يستخدم 2x للتكبير حتى الضعف و4x لما فوقه. الترخيص: CC BY-NC-SA 4.0، للاستخدام غير التجاري فقط.',
    'APISR (CVPR 2024) by Kiteretsu77, ONNX conversion by Xenova (the original is a PyTorch file). It redraws the image the way anime is produced: thick dark lines and stronger contrast. It looks clean, but it changes the drawing style, and the LoRA would learn that style. Two versions, 2x (18 MB) and 4x (6.5 MB); Automatic uses 2x for enlargements up to double and 4x above. License: GPL-3.0.':
        'APISR (CVPR 2024) من Kiteretsu77، نسخة ONNX حوّلها Xenova (الأصل ملف PyTorch). يعيد رسم الصورة بطريقة إنتاج الأنمي: خطوط داكنة سميكة وتباين أقوى. تبدو النتيجة نظيفة، لكنه يغيّر أسلوب الرسم، وستتعلم LoRA هذا الأسلوب. له نسختان، 2x (18 MB) و4x (6.5 MB)؛ والخيار «تلقائي» يستخدم 2x للتكبير حتى الضعف و4x لما فوقه. الترخيص: GPL-3.0.',
    'CDC_anime by 7eu7d7: the CDC enlarging method (Component Divide-and-Conquer, 2020) trained on anime, in the ONNX version published by deepghs. ALDS used it for upscaling up to version 0.4.1. It adds grain and can distort small details such as eyes and lines, and it needs much more graphics memory than the other models. 4x only, 160 MB to download. License: MIT.':
        'CDC_anime من 7eu7d7: طريقة التكبير CDC (Component Divide-and-Conquer، عام 2020) مدرَّبة على الأنمي، بنسخة ONNX التي نشرتها deepghs. استخدمه ALDS للتكبير حتى الإصدار 0.4.1. يضيف حبيبات وقد يشوّه التفاصيل الصغيرة مثل العيون والخطوط، ويحتاج ذاكرة من كرت الشاشة أكبر بكثير من باقي الموديلات. نسخة 4x فقط، والتحميل 160 MB. الترخيص: MIT.',
    "waifu2x (closest to the original)": "waifu2x (الأقرب إلى الأصل)",
    "Real-ESRGAN animevideov3 (crisper lines)": "Real-ESRGAN animevideov3 (خطوط أوضح)",
    "AnimeSharp (sharp)": "AnimeSharp (حاد)",
    "APISR (redraws lines, changes the style)": "APISR (يعيد رسم الخطوط ويغيّر الأسلوب)",
    "CDC (adds grain, can distort details)": "CDC (يضيف حبيبات وقد يشوّه التفاصيل)",
    "Enlarge every scene smaller than this to it (pixels; use your training resolution)":
        "كبّر كل مشهد أصغر من هذا الحجم إليه (بكسل؛ اجعله بدقة التدريب)",
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
    "Smallest character in the scene (% of the frame height)": "أصغر حجم للشخصية في المشهد (% من ارتفاع الإطار)",
    "Scenes where the character is smaller are left out. Only scenes where the character is alone are used.":
        "تُستبعد المشاهد التي تكون فيها الشخصية أصغر. وتُستخدم فقط المشاهد التي تظهر فيها الشخصية وحدها.",
    "Follow the character within a shot": "تتبّع الشخصية داخل اللقطة",
    "1 = off (recommended). Higher takes more frames from the same shot, but may let other characters in.":
        "1 = متوقف (يُنصح به). أعلى = إطارات أكثر من اللقطة نفسها، لكن قد تدخل شخصيات أخرى.",
    "Tagging model": "موديل الوسوم",
    "EVA02_Large is the most accurate; the others are faster.": "EVA02_Large الأدق، والبقية أسرع.",
    "Options": "خيارات",
    "Leave out other characters, using the clusters you didn't pick":
        "استبعاد الشخصيات الأخرى اعتمادًا على المجموعات التي لم تخترها",
    "Separate outfits automatically (a tag per outfit after the trigger word)":
        "فصل الأزياء تلقائيًا (وسم لكل زي بعد كلمة التفعيل)",
    "Put anime screencap at the start of every caption": "وسم anime screencap في أول كل وصف",
    "Keep images with text on screen": "إبقاء الصور التي فيها نصوص",
    "Keep chibi and blurry drawings": "إبقاء الرسم المصغّر (chibi) والضبابي",
    "Keep black-and-white and sepia images (flashbacks)": "إبقاء الصور بالأبيض والأسود والبني (مشاهد الذكريات)",
    "Save the left-out images in a {folder} folder": "حفظ الصور المستبعدة في مجلد {folder}",
    "Analyse from scratch, ignore the saved analysis (much slower, rarely needed)":
        "إعادة التحليل من الصفر وتجاهل المحفوظ (أبطأ بكثير، نادرًا ما تحتاجه)",
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
    "Image: {crop} — episode {ep} at {at} — match score {score} (lower is better) — sharpness {sharp}":
        "الصورة: {crop} — الحلقة {ep} عند {at} — درجة التطابق {score} (الأقل أفضل) — الحدة {sharp}",
    "Whole scene": "المشهد كاملًا",
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
    "🧹 Forget all images rejected as another character": "🧹 نسيان كل الصور المرفوضة كشخصية أخرى",
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
    "Every tag the tagger found is in the captions. Pick what the LoRA is for to see the tags that matter for it, "
    "then move the ones the trigger word should learn into the trigger word. Below are all the tags and how often "
    "they appear: remove, replace or add tags in **all** captions at once. Every change can be undone.":
        "كل وسم وجده الموسِّم موجود في الأوصاف. اختر غرض اللورا لتظهر الوسوم المهمة له، ثم انقل ما تريد أن "
        "تتعلمه كلمة التفعيل إليها. وفي الأسفل كل الوسوم وعدد مرات ظهورها: احذف أو استبدل أو أضف وسومًا في "
        "**كل** الأوصاف دفعة واحدة. كل تعديل يمكن التراجع عنه.",
    "What is the LoRA for?": "ما غرض اللورا؟",
    "🧑 Character": "🧑 شخصية",
    "🖌 Style": "🖌 ستايل",
    "👕 Outfit": "👕 ملابس",
    "Tags for this goal (checked = in at least 20% of the images)":
        "وسوم هذا الغرض (المؤشَّر عليها = تظهر في 20% من الصور على الأقل)",
    "🔒 Move the checked into the trigger word": "🔒 انقل المؤشَّر عليها إلى كلمة التفعيل",
    "🔒 Learned by the trigger word (not in the captions)": "🔒 تتعلّمها كلمة التفعيل (ليست في الأوصاف)",
    "↩ Put the checked back in the captions": "↩ أعد المؤشَّر عليها إلى الأوصاف",
    "🔒 Move the selected into the trigger word": "🔒 انقل المحدد إلى كلمة التفعيل",
    "No tags of this kind in the captions.": "لا توجد وسوم من هذا النوع في الأوصاف.",
    "Removed from every caption, so the trigger word learns them as part of the character. The number is how many "
    "images had the tag. Check a tag and put it back to return it to those images.":
        "حُذفت من كل الأوصاف، فتتعلمها كلمة التفعيل كجزء من الشخصية. الرقم هو عدد الصور التي كان فيها الوسم. "
        "ضع علامة على وسم وأعده ليرجع إلى تلك الصور في مكانه.",
    "Empty. Tags you move here are removed from every caption, so the trigger word learns them as part of the "
    "character.":
        "فارغة. الوسوم التي تنقلها إلى هنا تُحذف من كل الأوصاف، فتتعلمها كلمة التفعيل كجزء من الشخصية.",
    "Removed when these images were made by an older version: {tags}. Rebuild the character to get every tag back "
    "in the captions.":
        "حُذفت عند صنع هذه الصور بإصدار أقدم: {tags}. أعد بناء الشخصية لتعود كل الوسوم إلى الأوصاف.",
    "Pick one or more tags first": "اختر وسمًا أو أكثر أولًا",
    "The trigger word, the series and the outfit tags stay in the captions":
        "كلمة التفعيل واسم السلسلة ووسوم الأزياء تبقى في الأوصاف",
    "Moved into the trigger word: {tags}. Changed {n} captions.": "نُقل إلى كلمة التفعيل: {tags}. عُدّل {n} وصف.",
    "Put back in the captions: {tags}. Changed {n} captions.": "أُعيد إلى الأوصاف: {tags}. عُدّل {n} وصف.",
    "hair colour": "لون الشعر",
    "hair length": "طول الشعر",
    "haircut and hairstyle": "قصة الشعر وتسريحته",
    "hair ties and accessories": "ربطات الشعر وإكسسواراته",
    "eyes and eyebrows": "العينان والحاجبان",
    "tattoos, scars and marks": "الوشم والندوب والعلامات",
    "earrings and piercings": "الأقراط والثقوب",
    "makeup and nails": "المكياج والأظافر",
    "body": "الجسم",
    "clothes and accessories": "الملابس والإكسسوارات",
    "drawing style": "أسلوب الرسم",
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
    "- Upscaled with {model}: {n}": "- مُكبّرة بموديل {model}: {n}",
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
