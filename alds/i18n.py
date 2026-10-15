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
    "Settings or your review changed. Run the preview again to see the new result.":
        "تغيّرت الإعدادات أو مراجعتك. شغّل المعاينة مجددًا لترى النتيجة الجديدة.",
    "✅ Definitely this character": "✅ هذه الشخصية بالتأكيد",
    "✅ Confirmed images and the effect of your review": "✅ الصور المؤكدة وأثر مراجعتك",
    "Confirm clear images from different angles and in different outfits. Images marked ❓ come first under “All”.":
        "أكّد صورًا واضحة من زوايا مختلفة وبأزياء مختلفة. الصور المعلّمة ❓ تظهر أولًا في «الكل».",
    "Confirmed images": "الصور المؤكدة",
    "↶ Remove this confirmation": "↶ إلغاء هذا التأكيد",
    "🔎 Preview the effect": "🔎 عاين الأثر",
    "Frames that change (when the frames are still on disk)": "الإطارات التي تتغير (إن كانت الإطارات ما زالت محفوظة)",
    "See how your confirmations and rejections change the frames that match the character in the next build. Nothing "
    "changes until you build again. The counts are frames, before the scene filters.":
        "اعرف كيف تغيّر تأكيداتك ورفضك الإطاراتِ التي تطابق الشخصية في البناء القادم. لا يتغير شيء حتى تعيد البناء. "
        "الأعداد للإطارات قبل فلاتر المشاهد.",
    "Press “Preview the effect” after confirming or rejecting images.": "اضغط «عاين الأثر» بعد تأكيد صور أو رفضها.",
    "Matched frames: {before} → {after}. New: {added}; excluded: {removed}; different person: {switched}.":
        "الإطارات المطابقة: {before} ← {after}. جديدة: {added}؛ مستبعدة: {removed}؛ تغيّر الشخص المختار: {switched}.",
    "{confirmed} confirmed and {rejected} rejected images. Up to 24 changed frames are shown.":
        "{confirmed} صورة مؤكدة و{rejected} مرفوضة. تُعرض حتى ٢٤ إطارًا متغيرًا.",
    "Match score: {score} (lower = closer to the character).": "درجة التطابق: {score} (الأقل = أقرب إلى الشخصية).",
    "✅ You confirmed this character.": "✅ أكّدتَ هوية هذه الشخصية.",
    "❓ Check who this is: a weak match, or close to another character.":
        "❓ تحقق من هويتها: التطابق ضعيف، أو قريب من شخصية أخرى.",
    "- Images marked ❓ (unsure who it is) and ⚠ (to check) come first: look at them before the rest.\n- **✅ "
    "Definitely this character** confirms a clear image, and the program learns from it.\n- **🚫 N** removes another "
    "character and learns to leave out what looks like it. **🗑 Delete** removes a bad image.\n- **← →** move between "
    "images, **Ctrl+Z** undoes a removal.":
        "- الصور المعلّمة ❓ (هوية غير مؤكدة) و⚠ (للمراجعة) تظهر أولًا: راجعها قبل غيرها.\n- **✅ هذه الشخصية "
        "بالتأكيد** يؤكد صورة واضحة، فيتعلم منها البرنامج.\n- **🚫 N** يحذف صورة شخصية أخرى ويتعلم استبعاد ما يشبهها. "
        "**🗑 Delete** يحذف صورة سيئة.\n- **← →** للتنقل بين الصور، و**Ctrl+Z** للتراجع عن الحذف.",
    "Gap to the closest other character: {margin} (bigger = clearer).":
        "الفارق عن أقرب شخصية أخرى: {margin} (الأكبر أوضح).",
    " · {n} confirmed": " · {n} مؤكدة",
    "❓ Unsure who it is ({n})": "❓ هوية غير مؤكدة ({n})",
    "✅ Confirmed ({n})": "✅ مؤكدة ({n})",
    "Confirmed. Preview the effect before you build again.": "تم التأكيد. عاين الأثر قبل أن تعيد البناء.",
    "Build this character once to save its identity features.":
        "أعد بناء هذه الشخصية مرة واحدة ليتعلم البرنامج من مراجعتك.",
    "Scan the episodes before previewing identity feedback.": "افحص الحلقات قبل معاينة الأثر.",
    "Pick a confirmed image.": "اختر صورة مؤكدة.",
    "Change": "التغيّر",
    "Time": "الوقت",
    "Score before": "الدرجة قبل",
    "Score after": "الدرجة بعد",
    "Before": "قبل",
    "After": "بعد",
    "new match": "مطابقة جديدة",
    "no longer matched": "لم يعد مطابقًا",
    "different person": "تغيّر الشخص المختار",
    "This character is already built. Tick “Build this character again”, or type another name.":
        "هذه الشخصية مبنية من قبل. فعّل «أعد بناء الشخصية»، أو اكتب اسمًا آخر.",
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
    "Build this character again (the current result is saved as a version, and your review carries over)":
        "أعد بناء الشخصية (تُحفظ النتيجة الحالية كنسخة، وتنتقل مراجعتك)",
    "🔎 Preview these settings": "🔎 عاين هذه الإعدادات",
    "🔎 Settings preview": "🔎 معاينة الإعدادات",
    "Preview 12 frames before building. Your finished images stay as they are.":
        "عاين ١٢ إطارًا قبل البناء. تبقى صورك النهائية كما هي.",
    "Accepted and excluded scenes": "المشاهد المقبولة والمستبعدة",
    "{frames} sampled frames · {accepted} accepted scenes. Duplicates are checked within this sample. Upscaling and outfit tags are applied in the full build.":
        "عينة من {frames} إطار · {accepted} مشهد مقبول. تُقارن المشاهد المكررة داخل العينة فقط، والتكبير ووسوم الأزياء تُطبّق في البناء الكامل.",
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
    "identity threshold": "لا تطابق الشخصية",
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
    "Scan at least one episode first (tab 1)": "افحص حلقة واحدة على الأقل أولًا (التبويب ١)",
    "That cluster number doesn't exist. Numbers change after every scan, refresh the page":
        "رقم المجموعة غير موجود. الأرقام تتغير بعد كل فحص، حدّث الصفحة",
    "There are no images in the uploaded references": "لا توجد صور في المراجع المرفوعة",
    "Not enough clear views to cluster": "لا توجد مشاهد واضحة كافية للتجميع",
    "The cluster didn't split this strongly, lower “Split strength”": "لم تنقسم المجموعة بهذه الشدة، اخفض «شدة التقسيم»",
    "The cluster is too small to split": "المجموعة أصغر من أن تُقسم",

    "1. Scan episodes": "١. فحص الحلقات",
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
    "🔁 Find the OP/ED again in the scanned episodes": "🔁 أعد البحث عن الشارة في الحلقات المفحوصة",
    "**Which frames are kept** (for new scans)": "**الإطارات التي تُحفظ** (للفحص القادم)",
    "Time between kept frames (seconds)": "الوقت بين الإطارات المحفوظة (ثانية)",
    "Lower = more frames from each scene. Higher = fewer frames and a faster scan.":
        "أقل = إطارات أكثر من كل مشهد. أعلى = إطارات أقل وفحص أسرع.",
    "Change needed to keep another frame": "التغيّر المطلوب لحفظ إطار آخر",
    "How different a frame must look from the last kept one. Lower = more, more similar frames. Higher = fewer.":
        "كم يجب أن يختلف الإطار عن آخر إطار محفوظ. أقل = إطارات أكثر ومتشابهة أكثر. أعلى = إطارات أقل.",
    "▶ Start scanning": "▶ ابدأ الفحص",
    "Episode": "الحلقة",
    "Length (min)": "المدة (دقيقة)",
    "Frames": "إطارات",
    "Left out automatically": "مستبعد تلقائيًا",
    "Episodes scanned in this project": "الحلقات المفحوصة في المشروع",
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
    "Starting the scan...": "بدء الفحص...",
    "Scan at least one episode first": "افحص حلقة واحدة على الأقل أولًا",
    "Comparing the episodes...": "مقارنة الحلقات...",
    "Select exactly one cluster (the mixed one), then press “Split”": "حدّد مجموعة واحدة فقط (المختلطة) ثم اضغط «قسّم»",
    "Extracted frames": "الإطارات المستخرجة",
    "Scan data": "بيانات الفحص",
    "Cluster images": "صور المجموعات",
    "Saved analysis for rebuilds": "التحليل المحفوظ لإعادة البناء",
    "Character {name}": "الشخصية {name}",
    "**Project size: {size}**": "**حجم المشروع: {size}**",
    "| Part | Size |": "| الجزء | الحجم |",

    "2. Pick the character": "٢. اختيار الشخصية",
    "Click a character's image to select it, click again to unselect. If the character shows up in more than one "
    "cluster (another outfit, say), pick all of them. **The numbers change after every scan.**":
        "اضغط على صورة الشخصية لتحديدها، واضغط مرة أخرى لإلغاء التحديد. إن ظهرت الشخصية في أكثر من مجموعة "
        "(زي مختلف مثلًا) فاختر كل مجموعاتها. **الأرقام تتغير بعد كل فحص.**",
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
    "Reference images of the character (optional, with the clusters or instead of them; useful for side characters)":
        "صور مرجعية للشخصية (اختياري، مع المجموعات أو بدلًا منها؛ تفيد للشخصيات الثانوية)",
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
    "Episode {ep} at {at} · sharpness {sharp}": "الحلقة {ep} عند {at} · الحدة {sharp}",
    " · enlarged ×{f}": " · مُكبّرة ×{f}",
    "Pick a character.": "اختر شخصية.",
    "**{n}** images · **{r}** to check · {d} deleted": "**{n}** صورة · **{r}** للمراجعة · {d} محذوفة",
    " · {n} rejected as another character": " · {n} مرفوضة كشخصية أخرى",
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
        "كل وسم وجده موديل الوسوم موجود في الأوصاف. اختر غرض اللورا لتظهر الوسوم المهمة له، ثم انقل ما تريد أن "
        "تتعلمه كلمة التفعيل إليها. وفي الأسفل كل الوسوم وعدد مرات ظهورها: احذف أو استبدل أو أضف وسومًا في "
        "**كل** الأوصاف دفعة واحدة. كل تعديل يمكن التراجع عنه.",
    "What is the LoRA for?": "ما غرض اللورا؟",
    "🧑 Character": "🧑 شخصية",
    "🖌 Style": "🖌 أسلوب الرسم",
    "👕 Outfit": "👕 الزي",
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
    "**{n}** captions · **{k}** different tags · {u} changes you can undo":
        "**{n}** وصف · **{k}** وسم مختلف · {u} تعديل يمكن التراجع عنه",
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

    "Step {i} of {n}: {title}": "الخطوة {i} من {n}: {title}",
    "Finding the character": "البحث عن الشخصية",
    "{n} reference images": "{n} صورة مرجعية",
    "{n} images you confirmed help to find the character": "{n} صورة أكّدتها تساعد في إيجاد الشخصية",
    "{n} frames show the character (match threshold {threshold})": "{n} إطار تظهر فيه الشخصية (حد التطابق {threshold})",
    ", {n} of them found by following the shot": "، منها {n} بتتبّع الشخصية داخل اللقطة",
    "{n} other clusters": "{n} مجموعة أخرى",
    "{n} images rejected in the review": "{n} صورة رفضتها في المراجعة",
    " and ": " و",
    "{n} frames left out because the character there looks more like someone else ({sources})":
        "استُبعد {n} إطار لأن الشخصية فيه تشبه شخصية أخرى أكثر ({sources})",
    "{n} more frames are just above the match threshold. Raising it to {value} would add them, but other "
    "characters may slip in.":
        "{n} إطار آخر فوق حد التطابق بقليل. رفع الحد إلى {value} يضيفها، لكن قد تدخل معها شخصيات أخرى.",
    "Checking each scene": "تحليل المشاهد",
    "scenes": "مشهد",
    "{kept} of {n} scenes kept. Only scenes with the character alone and at least {share} of the frame height are "
    "used.":
        "بقي {kept} من {n} مشهد. تُستخدم فقط المشاهد التي تظهر فيها الشخصية وحدها بارتفاع {share} من الإطار على الأقل.",
    "Left out: {reasons}": "المستبعدة: {reasons}",
    "{reason}: {n}": "{reason}: {n}",
    "✅ Preview ready: {accepted} of {frames} sampled frames accepted. Enlarging and outfits are done only in the "
    "full build.":
        "✅ المعاينة جاهزة: قُبل {accepted} من {frames} إطار في العينة. التكبير وفصل الأزياء يتمّان في البناء الكامل فقط.",
    "Saving the images and captions": "حفظ الصور والأوصاف",
    "Saving the images and captions, enlarging the small scenes": "حفظ الصور والأوصاف وتكبير المشاهد الصغيرة",
    "Saving the images": "حفظ الصور",
    "images": "صورة",
    "Small details were not checked again: {error}": "لم تُراجع التفاصيل الصغيرة مرة أخرى: {error}",
    "{n} images saved, {r} of them marked ⚠ to check": "حُفظت {n} صورة، منها {r} معلّمة ⚠ للمراجعة",
    "{n} small scenes enlarged to about {size} px with {model}": "كُبّر {n} مشهد صغير إلى نحو {size} بكسل بموديل {model}",
    "Small details also found by comparing the images: {tags}": "تفاصيل صغيرة وُجدت أيضًا بمقارنة الصور: {tags}",
    "Separating the outfits": "فصل الأزياء",
    "{token}: {n} images ({tags})": "{token}: {n} صورة ({tags})",
    "told apart by look only": "تُميَّز بالشكل فقط",
    "{n} images without a clear outfit get no outfit tag": "{n} صورة بلا زي واضح، فلا وسم زي لها",
    "One outfit only, or too little clothing in view: no outfit tags added":
        "زي واحد فقط، أو الملابس غير ظاهرة بما يكفي: لم تُضف وسوم أزياء",
    "✅ Done: {n} images of {name}.": "✅ اكتمل: {n} صورة للشخصية {name}.",
    "Shots and angles:": "اللقطات والزوايا:",
    "{shot}: {angles} (total {n})": "{shot}: {angles} (المجموع {n})",
    "Appearance tags (all stay in the captions; in the Tags tab you pick the ones {name} should learn): {tags}":
        "وسوم المظهر (كلها تبقى في الأوصاف، ومن تبويب الوسوم تختار ما تتعلمه {name}): {tags}",
    "Most common tags: {tags}": "الوسوم الأكثر تكرارًا: {tags}",
    "Your review was carried over: {removed} images removed, {changed} captions edited, {moved} images moved to "
    "another group":
        "نُقلت مراجعتك: {removed} صورة محذوفة، و{changed} وصف معدّل، و{moved} صورة منقولة لمجموعة أخرى",
    "; tag edits applied to {n} new captions": "؛ وطُبّقت تعديلات الوسوم على {n} وصف جديد",
    "Images now: {n}": "عدد الصور الآن: {n}",
    "The previous result was saved as version {id}.": "حُفظت النتيجة السابقة كنسخة {id}.",
    "✅ Restored version {id}. The result before it was saved as version {previous}.":
        "✅ استُعيدت النسخة {id}، وحُفظت النتيجة التي قبلها كنسخة {previous}.",
    "✅ Saved as version {id}.": "✅ حُفظت كنسخة {id}.",
    "↶ Everything this action made was removed; the project is as it was before.":
        "↶ حُذف كل ما صنعته هذه العملية، وعاد المشروع كما كان.",

    "Episode {i} of {n}: {name}": "الحلقة {i} من {n}: {name}",
    "Episode {i} of {n}: {name} is already scanned, skipped": "الحلقة {i} من {n}: {name} مفحوصة من قبل، تُخطّيت",
    "Reading the episode": "قراءة الحلقة",
    "Finding the characters": "البحث عن الشخصيات",
    "frames": "إطار",
    "{n} frames taken from {shots} shots ({minutes} min)": "أُخذ {n} إطار من {shots} لقطة ({minutes} دقيقة)",
    "{n} character appearances, {k} of them big enough to recognise":
        "{n} ظهور لشخصيات، منها {k} بحجم يكفي للتعرّف عليها",
    "{n} frames saved": "حُفظ {n} إطار",
    "; {n} frames without a character to recognise were not kept": "، ولم يُحفظ {n} إطار بلا شخصية يمكن التعرّف عليها",
    "Finding the opening and ending (OP/ED)": "البحث عن الشارة (OP/ED)",
    "Comparing the episodes": "مقارنة الحلقات",
    "seconds": "ثانية",
    "Episode {ep}: the video file is missing, so it can't be compared": "الحلقة {ep}: ملف الفيديو غير موجود، فلا يمكن مقارنتها",
    "Reading episode {ep} for the comparison (only the first time)...": "قراءة الحلقة {ep} للمقارنة (أول مرة فقط)...",
    "Only one episode, and no other episode in its folder to compare it with":
        "حلقة واحدة فقط، ولا توجد حلقة أخرى في مجلدها للمقارنة",
    "Reading {name} for the comparison (no frames are taken from it)...": "قراءة {name} للمقارنة (لا تؤخذ منها إطارات)...",
    "Episode {ep}: {parts}": "الحلقة {ep}: {parts}",
    "nothing found": "لم يُعثر على شيء",
    "{n} frames left out": "استُبعد {n} إطار",
    "OP/ED detection is off: every frame is used again": "اكتشاف الشارة متوقف: كل الإطارات مستخدمة من جديد",
    "{n} frames are used again but were deleted to save space; they stay unused until you restore the frames":
        "{n} إطار عاد للاستخدام لكنه حُذف لتوفير المساحة، ولن يُستخدم حتى تستعيد الإطارات",
    "Grouping the characters": "تجميع الشخصيات",
    "{n} clear views of characters": "{n} ظهور واضح للشخصيات",
    "{n} characters found; {k} views in groups smaller than {size} are hidden":
        "وُجدت {n} شخصية، وأُخفي {k} ظهور في مجموعات أصغر من {size}",
    "#{id}: {n} views, episodes {episodes}": "#{id}: {n} ظهور، في الحلقات {episodes}",
    "Drawing the character cards": "رسم بطاقات الشخصيات",
    "characters": "شخصية",
    "Cluster #{id} split into {parts}": "قُسّمت المجموعة #{id} إلى {parts}",
    "#{id} ({n} views)": "#{id} ({n} ظهور)",
    "; {n} views that fit nowhere were left out": "؛ واستُبعد {n} ظهور لم يناسب أي جزء",
    "Restoring the frames": "استعادة الإطارات",
    "✅ Restored {n} missing frames. Building and grouping work again.":
        "✅ استُعيد {n} إطار مفقود. البناء والتجميع يعملان من جديد.",
    "✅ Deleted {n} frames and freed {size}.": "✅ حُذف {n} إطار وتحرّرت {size}.",
    "✅ Saved {n} of {total} images in {folder}": "✅ حُفظت {n} من {total} صورة في {folder}",
    "⚠ {n} images have no caption file": "⚠ {n} صورة بلا ملف وصف",
    "In AI Toolkit, set the dataset folder to {folder} and the caption extension to txt. The captions already "
    "contain the trigger word {name}.":
        "في AI Toolkit اجعل مجلد البيانات (dataset) هو {folder} وامتداد ملفات الوصف txt. "
        "الأوصاف تحتوي كلمة التفعيل {name} مسبقًا.",
}
