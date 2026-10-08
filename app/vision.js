"use strict";
/* 视觉检测页和模型训练页。和 workbench.html 里的脚本共用 I18N、S、t()、h()、$()、api() 等工具。 */
(function () {

/* ---------- 文案 / UI strings ---------- */
Object.assign(I18N.zh, {
  "v.recipes": "检测方案:", "v.noRecipes": "recipes 文件夹里没有检测方案", "v.custom": "（自定义）",
  "v.svc.ready": "视觉服务已就绪　OpenCV {v}", "v.svc.starting": "视觉服务启动中…", "v.svc.exited": "视觉服务已退出（代码 {n}），报错在启动窗口里",
  "v.svc.disabled": "视觉组件未安装或未启用", "v.svc.disabledHint": "重新运行安装脚本（install.bat / install.sh）即可补装 OpenCV；config.json 里 start_vision 要保持 true。",
  "v.svc.noMl": "这个 OpenCV 不带训练模块（cv2.ml）。请安装 4.x 版本：pip install \"opencv-python-headless<5\"",
  "v.image": "图像", "v.drop": "点击选择图片，或把图片拖到这里、直接粘贴", "v.dropSmall": "支持 JPEG / PNG / BMP / WebP；也可以用下面的示例图先试一遍",
  "v.pick": "选择图片", "v.camera": "摄像头", "v.shoot": "拍照", "v.cancel": "取消", "v.demo": "示例图:", "v.demoNote": "示例图是程序合成的，只用来演示流程",
  "v.cameraFail": "打不开摄像头：{msg}", "v.imgFail": "图片读取失败：{msg}", "v.showAnnotated": "标注图", "v.showOriginal": "原图",
  "v.context": "补充信息（可选）", "v.contextPh": "图像里看不出来、但判定需要知道的事，例如：订单要求一级果；这批货明天发往超市。会原样写进素材交给模型。",
  "v.run": "检测", "v.running": "检测中…", "v.rulesOnly": "只按规则裁决，不调用模型", "v.needImage": "请先选择一张图片", "v.needVision": "视觉服务没有就绪",
  "v.recipeJson": "方案内容（可以直接改阈值和参数）", "v.apply": "应用修改", "v.revert": "恢复原样", "v.saveAs": "另存为我的方案", "v.delete": "删除这个方案",
  "v.badJson": "方案不是合法的 JSON：{msg}", "v.applied": "已应用，重新检测即可看到效果", "v.saved": "已保存为「{id}」", "v.deleted": "已删除", "v.edited": "已修改，未保存",
  "v.tab.verdict": "结论", "v.tab.measure": "测量与区域", "v.tab.state": "素材与题目", "v.tab.raw": "原始响应", "v.tab.selftest": "数字自检",
  "v.empty": "选一张图片，点「检测」，结论会显示在这里", "v.fail": "检测失败",
  "v.pass": "可以自动放行：规则与模型一致，没有临界或低置信度的项", "v.review": "建议人工复核", "v.passRules": "已按规则裁决",
  "v.modelDown": "判定模型这次没有给出答案（{msg}）。下面是只按规则得到的结论；没有绑定规则的题目没有答案。",
  "v.missingModel": "这个方案可以用识别模型「{name}」给区域分类，但它还没有训练。不影响规则裁决；训练后素材里会多出识别结果。",
  "v.prepare": "用合成样本训练一个示例模型", "v.preparing": "正在生成样本并训练…", "v.prepared": "示例模型已训练完成，交叉验证准确率 {acc}。", "v.prepareFail": "训练失败：{msg}",
  "v.missingFile": "方案里引用的检测模型文件不存在：{name}",
  "v.src.rule": "规则裁决", "v.src.model": "模型判定", "v.src.none": "没有结论",
  "v.agree": "规则与模型一致", "v.conflict": "规则与模型不一致", "v.flag.review": "建议复核", "v.flag.edge": "临界",
  "v.rule": "规则", "v.model": "模型", "v.standard": "判定标准", "v.conf": "置信度 {v}", "v.noModelAnswer": "没有答案",
  "v.reviewPick": "人工复核：正确答案是", "v.reviewSave": "记录", "v.reviewSaved": "已记录，这个方案累计 {n} 条复核记录",
  "v.quality": "图像质量", "v.qualityOk": "合格（清晰度 {s}，亮度 {b}）", "v.timing": "图像处理 {a} ms，判定模型 {b} ms，合计 {c} ms", "v.timingRules": "图像处理 {a} ms，合计 {c} ms",
  "v.th.item": "测量项", "v.th.value": "结果", "v.th.id": "#", "v.th.label": "识别类别", "v.th.area": "面积", "v.th.length": "长", "v.th.width": "宽", "v.th.elong": "长宽比",
  "v.regions": "区域：{name}", "v.regionsCount": "共 {n} 个", "v.regionsMore": "只列出前 {n} 个",
  "v.addSel": "把勾选的区域加入训练集", "v.addDataset": "数据集", "v.addLabel": "类别", "v.addBtn": "加入", "v.added": "已加入 {n} 张", "v.addNeed": "先勾选区域，并填写数据集和类别",
  "v.stateNote": "下面是实际发给判定模型的素材和题目。数字旁边的比较结论由数值层写好，题目里的判定标准和它逐条对应。",
  "v.openText": "在「文本判定」页打开", "v.copy": "复制",
  "v.st.intro": "自检会在每个阈值两侧自动生成边界用例（刚好高于、刚好低于、远离阈值），交给当前接口的判定模型，再和硬规则的结果对比。同一批用例跑两遍：一遍只给数值，一遍带上数值层写好的比较结论。",
  "v.st.cost": "一次自检会调用模型约 {n} 次；远程接口按条计费。",
  "v.st.run": "运行自检", "v.st.running": "自检中…", "v.st.none": "这个方案没有绑定硬规则的题目，没有可自检的内容。", "v.st.never": "还没有运行过自检。",
  "v.st.last": "上次自检：{time}　用例 {n} 个　模型 {model}", "v.st.th.q": "题目", "v.st.th.raw": "只给数值", "v.st.th.cmp": "带比较结论", "v.st.th.near": "其中贴近阈值",
  "v.st.th.advice": "建议", "v.st.advise": "可交给模型", "v.st.enforce": "保持规则裁决",
  "v.st.explain": "「只给数值」一列反映模型自己比较数字的能力；「带比较结论」一列反映它能否读懂写好的结论。一致率低于 {th} 的题目应保持规则裁决（方案里 bindings 的默认设置）。",
  "v.st.misses": "带比较结论时仍答错的用例", "v.st.expected": "应为 {a}，模型答 {b}", "v.st.fail": "自检失败：{msg}",
  "v.export": "导出微调数据（JSONL）", "v.exportNote": "内容是自检用例（答案来自规则）加上人工复核记录，每行一条 {state, questions, gold}。",
  "vm.title": "模型", "vm.decision": "决策模型", "vm.classifier": "区域分类模型", "vm.detector": "检测模型", "vm.group": "应用到区域组", "vm.outGroup": "输出区域组名", "vm.conf": "置信度",
  "vm.addCount": "同时添加计数测量项", "vm.add": "加入方案", "vm.remove": "移除", "vm.loading": "正在读取模型列表…", "vm.goTrain": "去训练",
  "vm.noCls": "还没有训练好的分类模型，去「视觉训练 → 区域分类」训练", "vm.noDet": "还没有训练好的检测模型，去「视觉训练 → 目标检测」训练", "vm.noGroups": "这个方案里还没有区域组（先加 regions 或 detect 步骤）",
  "vm.added": "已加入，点「检测」生效；要长期保留请「另存为我的方案」", "vm.removed": "已移除，点「检测」生效；要长期保留请「另存为我的方案」",
  "vm.inRecipe": "方案里的模型步骤：", "vm.stepClassify": "classify  {m}  →  regions:{g}", "vm.stepDetect": "detect  {m}  →  regions:{g}", "vm.countLabel": "{g} 数量",
  "vm.note": "决策模型就是页面顶部「模型」框里的那个；分类 / 检测模型来自「视觉训练」页，加进方案后由视觉服务在分析时调用。",
  "v.yes": "是", "v.no": "否",
  "demo.ripe": "成熟", "demo.turning": "转色", "demo.unripe": "未熟", "demo.blemished": "有病斑", "demo.clean": "无草", "demo.light": "少量杂草", "demo.heavy": "杂草多",
  "demo.low": "虫少", "demo.medium": "中等", "demo.high": "虫多", "demo.ok": "完好", "demo.minor": "轻微缺陷", "demo.reject": "严重缺陷",
  "t.status": "训练环境", "t.backbone": "深度特征骨干网络", "t.bbReady": "已就绪（{file}，{dim} 维）", "t.bbMissing": "还没有下载",
  "t.bbNote": "「深度特征」用一个预训练的 MobileNetV2（约 14 MB）提取特征，外观复杂的目标（害虫种类、杂草种类）识别率高得多。下载一次即可；也可以把别的分类网络的 .onnx 放进 data/backbones/。",
  "t.bbDownload": "下载骨干网络", "t.bbDownloading": "下载中 {p}", "t.bbDone": "骨干网络已下载", "t.bbFail": "下载失败：{msg}。可以手动下载 .onnx 文件放进 data/backbones/ 文件夹。", "t.bbBad": "文件无法读取：{msg}",
  "t.datasets": "数据集", "t.dataset": "数据集", "t.newDataset": "新数据集的名字", "t.create": "新建", "t.noDataset": "还没有数据集。新建一个，或者先生成一份合成样本看看流程。",
  "t.addClass": "新类别的名字", "t.addClassBtn": "添加类别并选择图片", "t.addImages": "添加图片", "t.delClass": "删除类别", "t.delDataset": "删除数据集", "t.confirm": "确认删除",
  "t.count": "{n} 张", "t.dropHere": "可以把图片直接拖到某个类别上", "t.uploading": "正在上传 {a} / {b}…", "t.uploaded": "已添加 {n} 张", "t.needName": "请先填写名字",
  "t.demoGen": "生成合成样本", "t.demoScene": "场景", "t.generating": "正在生成…", "t.generated": "已生成数据集「{name}」。",
  "t.advice": "每类至少 2 张才能训练，建议每类 30 张以上；拍摄距离、光照尽量和实际使用时一致。",
  "t.train": "训练", "t.modelName": "模型名字", "t.features": "特征", "t.algo": "分类器", "t.augment": "翻转增强", "t.rotate": "旋转增强（目标朝向无关时勾选）",
  "t.f.color": "颜色", "t.f.texture": "纹理", "t.f.hog": "轮廓梯度 (HOG)", "t.f.shape": "形状与大小", "t.f.deep": "深度特征",
  "t.a.svm": "SVM（推荐）", "t.a.rtrees": "随机森林", "t.a.knn": "K 近邻",
  "t.start": "开始训练", "t.training": "训练中…", "t.stage.load": "读取图片", "t.stage.features": "提取特征", "t.stage.validate": "交叉验证", "t.stage.fit": "训练最终模型",
  "t.stage.generate": "生成样本", "t.stage.download": "下载", "t.stage.done": "完成", "t.fail": "训练失败：{msg}", "t.needDataset": "请先选择数据集", "t.needDeep": "勾选了深度特征，但骨干网络还没下载",
  "t.result": "训练结果", "t.acc": "交叉验证准确率", "t.accNote": "{k} 折交叉验证，{n} 张图，用时 {s} 秒。这是在没见过的折上的表现，不是训练集自测。",
  "t.th.class": "类别", "t.th.n": "样本", "t.th.recall": "召回率", "t.th.precision": "精确率", "t.cm": "混淆矩阵（行 = 真实类别，列 = 识别结果）",
  "t.models": "已训练的模型", "t.noModels": "还没有模型", "t.modelMeta": "{classes} 类　{feats}　{algo}　准确率 {acc}　{time}", "t.delModel": "删除",
  "t.test": "试一张图", "t.testResult": "识别为「{label}」，概率 {p}", "t.useNote": "在检测方案的 pipeline 里加一步 {\"op\": \"classify\", \"model\": \"模型名字\", \"on\": \"regions:区域名\"} 就能用它给区域分类。",
  "t.synthNote": "合成样本比真实照片干净得多，在它上面得到的准确率不代表真实场景的表现。",
  "t.stage.prepare": "读取数据", "t.stage.train": "训练", "t.stage.evaluate": "评估", "t.stage.save": "保存",
  "det.tab.cls": "区域分类", "det.tab.det": "目标检测",
  "det.env.ready": "检测训练环境就绪：torch {t}，torchvision {tv}，设备 {dev}", "det.env.missing": "没有安装 torch / torchvision（{why}），不能训练和使用检测模型。重新运行安装脚本并在 config.json 里开启 install_training 即可补装；数据集标注不受影响。",
  "det.intro": "目标检测模型能在一张图里框出每个目标并标出类别，适合目标数量多、形状不规则、靠分割难以分开的场景。流程：建数据集 → 画框标注（或用方案预标注、合成样本）→ 训练 → 在方案的 pipeline 里加一步 detect。",
  "det.datasets": "检测数据集", "det.newName": "新数据集的名字", "det.newClasses": "类别，逗号分隔（可留空，标注时再加）", "det.create": "新建", "det.noDataset": "还没有检测数据集。新建一个，或生成一份合成样本看看流程。",
  "det.meta": "{n} 张图　{b} 个框　类别：{c}", "det.noClasses": "（还没有类别）", "det.delDataset": "删除数据集", "det.confirm": "确认删除", "det.needName": "请先填写名字",
  "det.demoGen": "生成合成样本", "det.demoCount": "张数", "det.generating": "正在生成…", "det.generated": "已生成检测数据集「{name}」：{n} 张图，{b} 个框。",
  "det.items": "已标注的图片", "det.itemsCount": "共 {n} 张，显示 {a}–{b}", "det.prevPage": "上一页", "det.nextPage": "下一页", "det.noItems": "这个数据集还没有图片。在下面的标注器里选一张图开始画框。",
  "det.labeler": "标注器", "det.pick": "选择图片", "det.drop": "点击选择图片，或把图片拖到这里、直接粘贴；也可以点上面的缩略图打开已有的图", "det.dropSmall": "在图上拖动鼠标画框；点一个框选中它，按 Delete 删除",
  "det.cls": "当前类别", "det.newClass": "新类别名", "det.addClass": "添加", "det.needClass": "请先选择或添加一个类别", "det.boxCls": "选中框的类别", "det.delBox": "删除选中的框", "det.clear": "清空所有框",
  "det.boxes": "{n} 个框", "det.save": "保存标注", "det.saved": "已保存", "det.unsaved": "有未保存的修改", "det.saveFirst": "先保存这张图到数据集，再用方案预标注",
  "det.prev": "上一张", "det.next": "下一张", "det.delImage": "从数据集删除这张图", "det.prelabel": "从方案预标注", "det.prelabelHint": "用方案里的分割 / 识别步骤给出候选框，再手动修正。方案里的识别模型没训练时，框的类别是区域名。",
  "det.prelabeled": "预标注得到 {n} 个候选框，请检查后保存", "det.recipe": "方案", "det.imgFail": "图片读取失败：{msg}",
  "det.train": "训练检测模型", "det.modelName": "模型名字", "det.arch": "网络", "det.arch.ssdlite": "SSDLite · MobileNetV3（快，推荐，4G 显存够）", "det.arch.fasterrcnn_mobile": "Faster R-CNN · MobileNetV3 320（略准、略慢）",
  "det.epochs": "轮数", "det.batch": "批大小", "det.imgsz": "输入尺寸", "det.pretrained": "预训练权重", "det.pre.auto": "自动（下载不到就从头训练）", "det.pre.yes": "必须用（下载不到就报错）", "det.pre.no": "不用（从头训练）",
  "det.holdout": "留出验证比例", "det.resume": "从上次断点继续", "det.start": "开始训练", "det.training": "训练中…", "det.cancel": "取消", "det.cancelled": "已取消", "det.needDataset": "请先选择数据集", "det.needBoxes": "数据集里还没有标注框",
  "det.progress": "第 {e}/{es} 轮　步 {s}/{ss}　损失 {l}　预计剩余 {eta}", "det.log": "日志", "det.fail": "训练失败：{msg}",
  "det.result": "训练结果", "det.map": "mAP@0.5（留出集）", "det.mapNone": "没有留出验证集，未评估", "det.resultNote": "{n} 轮，{tr} 张训练图，{ho} 张验证图，用时 {s} 秒{pre}。", "det.preUsed": "，用了预训练权重", "det.preNo": "，从头训练",
  "det.th.class": "类别", "det.th.ap": "AP@0.5", "det.oomNote": "训练中显存不足 {n} 次，批大小自动降到 {b}。",
  "det.models": "检测模型", "det.noModels": "还没有检测模型", "det.modelMeta": "{arch}　{n} 类　mAP@0.5 {m}　{time}", "det.test": "试一张图", "det.testResult": "检出 {n} 个目标（置信度 ≥ {c}）", "det.delModel": "删除",
  "det.useNote": "在检测方案的 pipeline 里加一步 {\"op\": \"detect\", \"model\": \"模型名字\", \"conf\": 0.4, \"as\": \"regions:objects\"} 就能用它框出目标；后面的 count / class_count / measure 步骤照常引用 regions。可用 \"classes\": [\"weed\"] 只保留某几类。",
  "det.synthNote": "合成样本比真实照片干净得多，在它上面的 mAP 不代表真实场景的表现；要在真实场景使用，请用自己拍的图标注后训练。",
  "det.conf": "置信度阈值"
});
Object.assign(I18N.en, {
  "v.recipes": "Recipes:", "v.noRecipes": "No inspection recipes in the recipes folder", "v.custom": " (custom)",
  "v.svc.ready": "Vision service ready, OpenCV {v}", "v.svc.starting": "Vision service starting…", "v.svc.exited": "The vision service exited (code {n}); the error is in the launcher window",
  "v.svc.disabled": "Vision components not installed or not enabled", "v.svc.disabledHint": "Run the installer (install.bat / install.sh) again to add OpenCV; keep start_vision true in config.json.",
  "v.svc.noMl": "This OpenCV build has no training module (cv2.ml). Install a 4.x build: pip install \"opencv-python-headless<5\"",
  "v.image": "Image", "v.drop": "Click to choose an image, drop one here, or paste it", "v.dropSmall": "JPEG / PNG / BMP / WebP. The sample images below let you try the flow first",
  "v.pick": "Choose image", "v.camera": "Camera", "v.shoot": "Capture", "v.cancel": "Cancel", "v.demo": "Samples:", "v.demoNote": "Sample images are synthetic and only demonstrate the flow",
  "v.cameraFail": "Cannot open the camera: {msg}", "v.imgFail": "Could not read the image: {msg}", "v.showAnnotated": "Annotated", "v.showOriginal": "Original",
  "v.context": "Context (optional)", "v.contextPh": "Things the image cannot show but the decision needs, e.g. the order requires grade 1; this batch ships to a supermarket tomorrow. Passed to the model as written.",
  "v.run": "Inspect", "v.running": "Inspecting…", "v.rulesOnly": "Decide by rules only, do not call the model", "v.needImage": "Choose an image first", "v.needVision": "The vision service is not ready",
  "v.recipeJson": "Recipe (edit thresholds and parameters here)", "v.apply": "Apply", "v.revert": "Revert", "v.saveAs": "Save as my recipe", "v.delete": "Delete this recipe",
  "v.badJson": "The recipe is not valid JSON: {msg}", "v.applied": "Applied; inspect again to see the effect", "v.saved": "Saved as \"{id}\"", "v.deleted": "Deleted", "v.edited": "edited, not saved",
  "v.tab.verdict": "Verdict", "v.tab.measure": "Measurements", "v.tab.state": "Material and questions", "v.tab.raw": "Raw response", "v.tab.selftest": "Numeric self-test",
  "v.empty": "Choose an image and press Inspect; the verdict appears here", "v.fail": "Inspection failed",
  "v.pass": "Can pass automatically: rule and model agree, nothing borderline or low-confidence", "v.review": "Human review recommended", "v.passRules": "Decided by rules",
  "v.modelDown": "The decision model gave no answer this time ({msg}). Below is the rule-only result; questions without a bound rule have no answer.",
  "v.missingModel": "This recipe can classify regions with the recognition model \"{name}\", which has not been trained yet. Rule decisions are unaffected; once trained, recognition results are added to the material.",
  "v.prepare": "Train a sample model from synthetic images", "v.preparing": "Generating samples and training…", "v.prepared": "Sample model trained; cross-validated accuracy {acc}.", "v.prepareFail": "Training failed: {msg}",
  "v.missingFile": "The detector file referenced by the recipe does not exist: {name}",
  "v.src.rule": "Decided by rule", "v.src.model": "Decided by model", "v.src.none": "No verdict",
  "v.agree": "rule and model agree", "v.conflict": "rule and model disagree", "v.flag.review": "review", "v.flag.edge": "borderline",
  "v.rule": "Rule", "v.model": "Model", "v.standard": "Standard", "v.conf": "confidence {v}", "v.noModelAnswer": "no answer",
  "v.reviewPick": "Human review: the correct answer is", "v.reviewSave": "Record", "v.reviewSaved": "Recorded; this recipe now has {n} review records",
  "v.quality": "Image quality", "v.qualityOk": "ok (sharpness {s}, brightness {b})", "v.timing": "Image processing {a} ms, decision model {b} ms, total {c} ms", "v.timingRules": "Image processing {a} ms, total {c} ms",
  "v.th.item": "Measurement", "v.th.value": "Result", "v.th.id": "#", "v.th.label": "Class", "v.th.area": "Area", "v.th.length": "Length", "v.th.width": "Width", "v.th.elong": "Elongation",
  "v.regions": "Regions: {name}", "v.regionsCount": "{n} in total", "v.regionsMore": "showing the first {n}",
  "v.addSel": "Add the ticked regions to a training set", "v.addDataset": "Dataset", "v.addLabel": "Class", "v.addBtn": "Add", "v.added": "Added {n} images", "v.addNeed": "Tick some regions and fill in the dataset and class first",
  "v.stateNote": "This is the material and the questions actually sent to the decision model. The comparison next to each number is written by the numeric layer, and the standard in each question mirrors it clause by clause.",
  "v.openText": "Open in Text decisions", "v.copy": "Copy",
  "v.st.intro": "The self-test generates boundary cases on both sides of every threshold (just above, just below, far away), sends them to the decision model of the current interface, and compares the answers with the hard rules. The same cases run twice: once with bare numbers, once with the comparisons written by the numeric layer.",
  "v.st.cost": "One self-test makes about {n} model calls; remote interfaces bill per call.",
  "v.st.run": "Run self-test", "v.st.running": "Testing…", "v.st.none": "This recipe has no question bound to a hard rule, so there is nothing to test.", "v.st.never": "No self-test has been run yet.",
  "v.st.last": "Last self-test: {time}, {n} cases, model {model}", "v.st.th.q": "Question", "v.st.th.raw": "Bare numbers", "v.st.th.cmp": "With comparisons", "v.st.th.near": "Near a threshold",
  "v.st.th.advice": "Advice", "v.st.advise": "model may decide", "v.st.enforce": "keep the rule",
  "v.st.explain": "\"Bare numbers\" shows how well the model compares numbers by itself; \"With comparisons\" shows whether it can read conclusions that are already written out. Questions below {th} agreement should stay rule-decided (the default in the recipe's bindings).",
  "v.st.misses": "Cases still answered wrong with comparisons", "v.st.expected": "expected {a}, model said {b}", "v.st.fail": "Self-test failed: {msg}",
  "v.export": "Export fine-tuning data (JSONL)", "v.exportNote": "Contains the self-test cases (answers come from the rules) plus human review records, one {state, questions, gold} per line.",
  "vm.title": "Models", "vm.decision": "Decision model", "vm.classifier": "Region classifier", "vm.detector": "Detector", "vm.group": "apply to regions", "vm.outGroup": "output regions", "vm.conf": "confidence",
  "vm.addCount": "also add a count measurement", "vm.add": "Add to recipe", "vm.remove": "Remove", "vm.loading": "Loading model lists…", "vm.goTrain": "Go to training",
  "vm.noCls": "No trained classifier yet; train one under Vision training → Region classification", "vm.noDet": "No trained detector yet; train one under Vision training → Object detection", "vm.noGroups": "This recipe has no regions group yet (add a regions or detect step first)",
  "vm.added": "Added; press Inspect to use it. Use \"Save as my recipe\" to keep it", "vm.removed": "Removed; press Inspect to use it. Use \"Save as my recipe\" to keep it",
  "vm.inRecipe": "Model steps in this recipe:", "vm.stepClassify": "classify  {m}  →  regions:{g}", "vm.stepDetect": "detect  {m}  →  regions:{g}", "vm.countLabel": "{g} count",
  "vm.note": "The decision model is the one in the Model box at the top of the page; classifiers and detectors come from the Vision training page and are run by the vision service during analysis once added to the recipe.",
  "v.yes": "Yes", "v.no": "No",
  "demo.ripe": "ripe", "demo.turning": "turning", "demo.unripe": "unripe", "demo.blemished": "blemished", "demo.clean": "no weeds", "demo.light": "few weeds", "demo.heavy": "many weeds",
  "demo.low": "few insects", "demo.medium": "moderate", "demo.high": "many insects", "demo.ok": "sound", "demo.minor": "minor defects", "demo.reject": "severe defects",
  "t.status": "Training environment", "t.backbone": "Backbone for deep features", "t.bbReady": "ready ({file}, {dim} dimensions)", "t.bbMissing": "not downloaded yet",
  "t.bbNote": "Deep features come from a pretrained MobileNetV2 (about 14 MB) and recognise visually complex targets (pest or weed species) far better. Download it once, or put another classification network's .onnx into data/backbones/.",
  "t.bbDownload": "Download backbone", "t.bbDownloading": "Downloading {p}", "t.bbDone": "Backbone downloaded", "t.bbFail": "Download failed: {msg}. You can download an .onnx file manually and put it into the data/backbones/ folder.", "t.bbBad": "The file cannot be read: {msg}",
  "t.datasets": "Datasets", "t.dataset": "Dataset", "t.newDataset": "Name of the new dataset", "t.create": "Create", "t.noDataset": "No datasets yet. Create one, or generate synthetic samples first to see the flow.",
  "t.addClass": "Name of the new class", "t.addClassBtn": "Add class and choose images", "t.addImages": "Add images", "t.delClass": "Delete class", "t.delDataset": "Delete dataset", "t.confirm": "Confirm delete",
  "t.count": "{n} images", "t.dropHere": "Images can be dropped straight onto a class", "t.uploading": "Uploading {a} / {b}…", "t.uploaded": "Added {n} images", "t.needName": "Enter a name first",
  "t.demoGen": "Generate synthetic samples", "t.demoScene": "Scene", "t.generating": "Generating…", "t.generated": "Dataset \"{name}\" generated.",
  "t.advice": "Each class needs at least 2 images to train; 30 or more per class is recommended. Keep distance and lighting close to real use.",
  "t.train": "Train", "t.modelName": "Model name", "t.features": "Features", "t.algo": "Classifier", "t.augment": "Flip augmentation", "t.rotate": "Rotation augmentation (when orientation does not matter)",
  "t.f.color": "Colour", "t.f.texture": "Texture", "t.f.hog": "Contour gradients (HOG)", "t.f.shape": "Shape and size", "t.f.deep": "Deep features",
  "t.a.svm": "SVM (recommended)", "t.a.rtrees": "Random forest", "t.a.knn": "K nearest neighbours",
  "t.start": "Start training", "t.training": "Training…", "t.stage.load": "reading images", "t.stage.features": "extracting features", "t.stage.validate": "cross-validating", "t.stage.fit": "fitting the final model",
  "t.stage.generate": "generating samples", "t.stage.download": "downloading", "t.stage.done": "done", "t.fail": "Training failed: {msg}", "t.needDataset": "Choose a dataset first", "t.needDeep": "Deep features are ticked, but the backbone has not been downloaded",
  "t.result": "Training result", "t.acc": "Cross-validated accuracy", "t.accNote": "{k}-fold cross-validation, {n} images, {s} s. This is performance on held-out folds, not on the training set.",
  "t.th.class": "Class", "t.th.n": "Samples", "t.th.recall": "Recall", "t.th.precision": "Precision", "t.cm": "Confusion matrix (rows = actual class, columns = prediction)",
  "t.models": "Trained models", "t.noModels": "No models yet", "t.modelMeta": "{classes} classes, {feats}, {algo}, accuracy {acc}, {time}", "t.delModel": "Delete",
  "t.test": "Try an image", "t.testResult": "Recognised as \"{label}\", probability {p}", "t.useNote": "Add a step {\"op\": \"classify\", \"model\": \"model name\", \"on\": \"regions:region name\"} to a recipe's pipeline to classify regions with it.",
  "t.synthNote": "Synthetic samples are far cleaner than real photos; accuracy on them says nothing about real-world performance.",
  "t.stage.prepare": "reading data", "t.stage.train": "training", "t.stage.evaluate": "evaluating", "t.stage.save": "saving",
  "det.tab.cls": "Region classification", "det.tab.det": "Object detection",
  "det.env.ready": "Detection training ready: torch {t}, torchvision {tv}, device {dev}", "det.env.missing": "torch / torchvision are not installed ({why}), so detection models cannot be trained or used. Run the installer again with install_training enabled in config.json; dataset labelling still works.",
  "det.intro": "An object detector draws a box around every target in an image and names its class. It suits scenes with many, irregular targets that segmentation cannot separate. Flow: create a dataset, draw boxes (or pre-label from a recipe / generate synthetic samples), train, then add a detect step to a recipe's pipeline.",
  "det.datasets": "Detection datasets", "det.newName": "Name of the new dataset", "det.newClasses": "Classes, comma separated (optional; add while labelling)", "det.create": "Create", "det.noDataset": "No detection datasets yet. Create one, or generate synthetic samples to see the flow.",
  "det.meta": "{n} images, {b} boxes, classes: {c}", "det.noClasses": "(no classes yet)", "det.delDataset": "Delete dataset", "det.confirm": "Confirm delete", "det.needName": "Enter a name first",
  "det.demoGen": "Generate synthetic samples", "det.demoCount": "Images", "det.generating": "Generating…", "det.generated": "Detection dataset \"{name}\" generated: {n} images, {b} boxes.",
  "det.items": "Labelled images", "det.itemsCount": "{n} in total, showing {a}–{b}", "det.prevPage": "Previous page", "det.nextPage": "Next page", "det.noItems": "This dataset has no images yet. Choose an image in the labeller below and start drawing boxes.",
  "det.labeler": "Labeller", "det.pick": "Choose image", "det.drop": "Click to choose an image, drop one here or paste it; or click a thumbnail above to open an existing image", "det.dropSmall": "Drag on the image to draw a box; click a box to select it, press Delete to remove it",
  "det.cls": "Current class", "det.newClass": "New class name", "det.addClass": "Add", "det.needClass": "Choose or add a class first", "det.boxCls": "Class of the selected box", "det.delBox": "Delete selected box", "det.clear": "Clear all boxes",
  "det.boxes": "{n} boxes", "det.save": "Save labels", "det.saved": "Saved", "det.unsaved": "unsaved changes", "det.saveFirst": "Save this image to the dataset first, then pre-label from a recipe",
  "det.prev": "Previous", "det.next": "Next", "det.delImage": "Remove this image from the dataset", "det.prelabel": "Pre-label from recipe", "det.prelabelHint": "Uses the recipe's segmentation / classification steps to propose boxes, which you then correct by hand. If the recipe's recognition model is not trained, boxes are labelled with the region name.",
  "det.prelabeled": "Pre-labelling proposed {n} boxes; check them and save", "det.recipe": "Recipe", "det.imgFail": "Could not read the image: {msg}",
  "det.train": "Train a detector", "det.modelName": "Model name", "det.arch": "Network", "det.arch.ssdlite": "SSDLite · MobileNetV3 (fast, recommended, fits 4 GB)", "det.arch.fasterrcnn_mobile": "Faster R-CNN · MobileNetV3 320 (a bit more accurate, slower)",
  "det.epochs": "Epochs", "det.batch": "Batch size", "det.imgsz": "Input size", "det.pretrained": "Pretrained weights", "det.pre.auto": "auto (train from scratch if the download fails)", "det.pre.yes": "required (fail if the download fails)", "det.pre.no": "none (train from scratch)",
  "det.holdout": "Holdout fraction", "det.resume": "Resume from the last checkpoint", "det.start": "Start training", "det.training": "Training…", "det.cancel": "Cancel", "det.cancelled": "Cancelled", "det.needDataset": "Choose a dataset first", "det.needBoxes": "The dataset has no boxes yet",
  "det.progress": "epoch {e}/{es}, step {s}/{ss}, loss {l}, about {eta} left", "det.log": "Log", "det.fail": "Training failed: {msg}",
  "det.result": "Training result", "det.map": "mAP@0.5 (holdout)", "det.mapNone": "No holdout set; not evaluated", "det.resultNote": "{n} epochs, {tr} training images, {ho} holdout images, {s} s{pre}.", "det.preUsed": ", with pretrained weights", "det.preNo": ", from scratch",
  "det.th.class": "Class", "det.th.ap": "AP@0.5", "det.oomNote": "Ran out of memory {n} times; batch size was reduced to {b}.",
  "det.models": "Detection models", "det.noModels": "No detection models yet", "det.modelMeta": "{arch}, {n} classes, mAP@0.5 {m}, {time}", "det.test": "Try an image", "det.testResult": "{n} objects detected (confidence ≥ {c})", "det.delModel": "Delete",
  "det.useNote": "Add a step {\"op\": \"detect\", \"model\": \"model name\", \"conf\": 0.4, \"as\": \"regions:objects\"} to a recipe's pipeline to detect objects with it; later count / class_count / measure steps use the regions as usual. \"classes\": [\"weed\"] keeps only some classes.",
  "det.synthNote": "Synthetic samples are far cleaner than real photos; mAP on them says nothing about real-world performance. For real use, label your own photos and train on them.",
  "det.conf": "Confidence threshold"
});

/* ---------- 状态 ---------- */
const V = {
  recipes: [], loaded: false, recipeId: null, text: "", applied: null, msg: null,
  image: null, camera: null, showAnnotated: true, context: "", rulesOnly: false,
  running: false, last: null, error: "", tab: "verdict", preparing: false, prepareMsg: null,
  selftest: {}, selfRunning: false, selfError: "", picked: {}, addDataset: "", addLabel: "", reviewMsg: {}, reviewPick: {}
};
const TR = {
  loaded: false, datasets: [], models: [], dataset: "", form: { name: "", features: ["color", "texture", "shape"], algo: "svm", augment: true, rotate: false },
  job: null, jobKind: "", result: null, msg: null, upload: "", scene: "fruit", confirm: "", test: {}, bbJob: null, bbMsg: null
};
const RECIPE_KEY = "laya-workbench-recipe";
try { V.recipeId = localStorage.getItem(RECIPE_KEY) || null; } catch (e) { /* 用第一个方案 */ }

async function jget(path) {
  const resp = await api(path, { cache: "no-store" });
  let data = null;
  try { data = await resp.json(); } catch (e) { /* 不是 JSON */ }
  return { ok: resp.ok, status: resp.status, data: data };
}
async function jpost(path, body, headers) {
  const resp = await api(path, { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, headers || {}), body: JSON.stringify(body) });
  let data = null;
  try { data = await resp.json(); } catch (e) { /* 不是 JSON */ }
  return { ok: resp.ok, status: resp.status, data: data };
}
function errText(res) {
  const d = res && res.data;
  if (d && d.detail != null) return typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail);
  return "HTTP " + (res ? res.status : 0);
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function pollJob(job, tick) {
  let cur = job;
  while (cur && (cur.state === "queued" || cur.state === "running")) {
    await sleep(500);
    const res = await jget("/v1/vision/jobs?id=" + encodeURIComponent(cur.id));
    if (!res.ok) return { state: "error", error: errText(res) };
    cur = res.data;
    if (tick) tick(cur);
  }
  return cur;
}
function vision() { return (S.status && S.status.vision) || null; }
function visionReady() { const v = vision(); return !!(v && v.health && (v.mode === "running" || v.mode === "external")); }
function stageName(stage) { const key = "t.stage." + stage; return I18N[LANG][key] || I18N.zh[key] ? t(key) : (stage || ""); }

function statusLine() {
  const v = vision();
  const line = h("div", { class: "vstatus" });
  if (S.status === undefined) { line.append(h("span", { class: "dot" }), t("s.connecting")); return line; }
  if (!S.status) { line.append(h("span", { class: "dot bad" }), t("s.offline")); return line; }
  if (visionReady()) {
    line.append(h("span", { class: "dot ok" }), t("v.svc.ready", { v: v.health.opencv }));
    if (!v.health.has_ml) line.append(h("span", { class: "hint warn" }, t("v.svc.noMl")));
  } else if (v && v.mode === "starting") line.append(h("span", { class: "dot wait" }), t("v.svc.starting"));
  else if (v && v.mode === "exited") line.append(h("span", { class: "dot bad" }), t("v.svc.exited", { n: v.exit_code }));
  else line.append(h("span", { class: "dot bad" }), t("v.svc.disabled"), h("span", { class: "hint" }, t("v.svc.disabledHint")));
  return line;
}

/* ---------- 图片 ---------- */
function fileToDataUrl(file, maxSide) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(reader.error ? reader.error.message : "read error"));
    reader.onload = () => {
      const url = String(reader.result);
      const img = new Image();
      img.onerror = () => resolve(url);                 // 浏览器不认识的格式（TIFF 等）原样交给服务端解码
      img.onload = () => {
        const side = Math.max(img.naturalWidth, img.naturalHeight);
        if (side <= maxSide) return resolve(url);
        const k = maxSide / side;
        const canvas = h("canvas", { width: Math.round(img.naturalWidth * k), height: Math.round(img.naturalHeight * k) });
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", 0.92));
      };
      img.src = url;
    };
    reader.readAsDataURL(file);
  });
}
function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("read error"));
    reader.onload = () => resolve(String(reader.result));
    reader.readAsDataURL(blob);
  });
}
function imageFiles(list) { return Array.from(list || []).filter(f => /^image\//.test(f.type) || /\.(jpe?g|png|bmp|webp|tiff?)$/i.test(f.name)); }
function setImage(url) { V.image = url; V.last = null; V.error = ""; V.picked = {}; V.showAnnotated = true; renderVision(); }
async function useFile(file) {
  if (!file) return;
  try { setImage(await fileToDataUrl(file, 2400)); } catch (e) { toast(t("v.imgFail", { msg: e.message })); }
}
async function useDemo(scene, variant) {
  try {
    const resp = await api("/v1/vision/demo?scene=" + encodeURIComponent(scene) + "&variant=" + encodeURIComponent(variant) + "&seed=" + Math.floor(Math.random() * 90000 + 1));
    if (!resp.ok) { let d = {}; try { d = await resp.json(); } catch (e) { /* 忽略 */ } throw new Error(d.detail || "HTTP " + resp.status); }
    setImage(await blobToDataUrl(await resp.blob()));
  } catch (e) { toast(t("v.imgFail", { msg: e.message })); }
}
function stopCamera() {
  if (V.camera) { V.camera.getTracks().forEach(track => track.stop()); V.camera = null; }
}
async function startCamera() {
  try {
    V.camera = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1920 } } });
    renderVision();
  } catch (e) { V.camera = null; toast(t("v.cameraFail", { msg: e.message || e.name })); }
}
function shoot() {
  const video = $("#v-video");
  if (!video || !video.videoWidth) return;
  const canvas = h("canvas", { width: video.videoWidth, height: video.videoHeight });
  canvas.getContext("2d").drawImage(video, 0, 0);
  stopCamera();
  setImage(canvas.toDataURL("image/jpeg", 0.92));
}

/* ---------- 方案 ---------- */
function recipeItem() { return V.recipes.find(r => r.id === V.recipeId) || null; }
function recipe() { return V.applied || (recipeItem() && recipeItem().recipe) || null; }
function selectRecipe(id) {
  V.recipeId = id; V.applied = null; V.msg = null; V.last = null; V.error = ""; V.picked = {}; V.prepareMsg = null;
  const item = recipeItem();
  V.text = item ? pretty(item.recipe) : "";
  try { localStorage.setItem(RECIPE_KEY, id); } catch (e) { /* 记不住也没关系 */ }
  loadSelftest();
}
let recipeSeq = 0;
async function loadRecipes(keep) {
  const seq = ++recipeSeq;
  const res = await jget("/_wb/recipes?lang=" + LANG);
  if (seq !== recipeSeq) return;
  V.recipes = res.ok && Array.isArray(res.data) ? res.data : [];
  V.loaded = true;
  const edited = keep && V.applied;
  if (!recipeItem()) V.recipeId = V.recipes.length ? V.recipes[0].id : null;
  if (!edited) selectRecipe(V.recipeId);
  renderVision();
}
async function loadSelftest() {
  const id = V.recipeId;
  if (!id) return;
  const res = await jget("/v1/inspect/selftest?recipe=" + encodeURIComponent(id));
  if (res.ok && res.data && res.data.levels) { V.selftest[id] = res.data; if (S.view === "vision" && V.tab === "selftest") renderResult(); }
}
function applyRecipeText() {
  try {
    const obj = JSON.parse(V.text);
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) throw new Error(t("e.top"));
    if (!obj.id) obj.id = V.recipeId;
    V.applied = obj; V.msg = { cls: "ok", text: t("v.applied") };
  } catch (e) { V.msg = { cls: "bad", text: t("v.badJson", { msg: e.message }) }; }
  renderVision();
}

/* ---------- 检测 ---------- */
function runProblem() {
  if (!visionReady()) return t("v.needVision");
  if (!recipe()) return t("v.noRecipes");
  if (!V.image) return t("v.needImage");
  return "";
}
async function runInspect() {
  if (V.running || runProblem()) return;
  V.running = true; V.error = ""; V.tab = V.tab === "selftest" ? "verdict" : V.tab; renderVision();
  const body = { recipe: V.applied || V.recipeId, image: V.image, use_model: !V.rulesOnly };
  if (V.context.trim()) body.context = V.context.trim();
  if (S.model.trim()) body.model = S.model.trim();
  if (S.minConf.trim() && isFinite(Number(S.minConf))) body.min_confidence = Number(S.minConf);
  try {
    const res = await jpost("/v1/inspect", body, { "X-WB-Target": S.target });
    if (res.ok && res.data) { V.last = res.data; V.picked = {}; V.reviewMsg = {}; V.reviewPick = {}; }
    else { V.last = null; V.error = errText(res); }
  } catch (e) { V.last = null; V.error = t("e.net", { msg: e.message || String(e) }); }
  V.running = false;
  renderVision();
}
async function prepareModel() {
  const r = recipe();
  if (!r || !r.train || V.preparing) return;
  V.preparing = true; V.prepareMsg = { cls: "", text: t("v.preparing") }; renderResult();
  const res = await jpost("/v1/vision/demo/prepare", r.train);
  let job = res.ok ? res.data : { state: "error", error: errText(res) };
  job = await pollJob(job, cur => { V.prepareMsg = { cls: "", text: t("v.preparing") + " " + stageName(cur.stage) + " " + Math.round((cur.progress || 0) * 100) + "%" }; renderResult(); });
  V.preparing = false;
  if (job.state === "done") {
    V.prepareMsg = { cls: "ok", text: t("v.prepared", { acc: pct(job.result.model.metrics.accuracy) }) + (LANG === "en" ? " " : "") + t("t.synthNote") };
    TR.loaded = false; VM.loaded = false;
    if (V.image) return runInspect();
  } else V.prepareMsg = { cls: "bad", text: t("v.prepareFail", { msg: job.error || "" }) };
  renderResult();
}
async function runSelftest() {
  if (V.selfRunning || !V.recipeId) return;
  V.selfRunning = true; V.selfError = ""; renderResult();
  const body = { recipe: V.applied || V.recipeId };
  if (S.model.trim()) body.model = S.model.trim();
  try {
    const res = await jpost("/v1/inspect/selftest", body, { "X-WB-Target": S.target });
    if (res.ok) V.selftest[V.recipeId] = res.data; else V.selfError = errText(res);
  } catch (e) { V.selfError = e.message || String(e); }
  V.selfRunning = false; renderResult();
}
async function saveReview(qid, value) {
  const run = V.last;
  if (!run) return;
  const gold = {}; gold[qid] = value;
  const res = await jpost("/v1/inspect/review", { recipe: run.recipe, state: run.state, questions: run.questions, gold: gold });
  V.reviewMsg[qid] = res.ok ? t("v.reviewSaved", { n: res.data.reviews }) : errText(res);
  renderResult();
}
async function addRegions(group) {
  const boxes = (V.last.analysis.regions[group] || []).filter(r => V.picked[group + ":" + r.id]).map(r => r.bbox);
  if (!boxes.length || !V.addDataset.trim() || !V.addLabel.trim()) { toast(t("v.addNeed")); return; }
  const r = recipe() || {};
  const res = await jpost("/v1/vision/datasets/add_regions", { dataset: V.addDataset.trim(), label: V.addLabel.trim(), image: V.image, boxes: boxes, max_side: r.max_side || 1280 });
  if (res.ok) { toast(t("v.added", { n: res.data.saved })); V.picked = {}; TR.loaded = false; renderResult(); } else toast(errText(res));
}

/* ---------- 视觉检测页的「模型」卡：选决策模型、把训练好的分类 / 检测模型加进方案 ---------- */
const VM = { loaded: false, loading: false, cls: [], det: [], clsModel: "", clsGroup: "", detModel: "", detGroup: "", detConf: "0.4", detCount: true, touched: false };
async function loadVisionModels() {
  if (!visionReady() || VM.loading) return;
  VM.loading = true;
  const [a, b] = await Promise.all([jget("/v1/vision/models"), jget("/v1/vision/det/models")]);
  VM.cls = a.ok ? a.data.models : [];
  VM.det = b.ok ? b.data.models : [];
  VM.loaded = true; VM.loading = false;
  if (!VM.cls.some(m => m.name === VM.clsModel)) VM.clsModel = VM.cls.length ? VM.cls[0].name : "";
  if (!VM.det.some(m => m.name === VM.detModel)) { VM.detModel = VM.det.length ? VM.det[0].name : ""; VM.touched = false; }
  if (S.view === "vision") renderVision();
}
function invalidateVisionModels() { VM.loaded = false; if (S.view === "vision") loadVisionModels(); }
/* 一步产出的区域组名：regions 的 name；detect 的 as（regions:名字）/ into / name，默认 objects；classify on=tiles 的 into */
function stepGroup(step) {
  if (!step || typeof step !== "object") return null;
  if (step.op === "regions") return step.name || null;
  if (step.op === "detect") {
    const target = String(step.as || step.into || step.name || "objects");
    return target.indexOf("regions:") === 0 ? target.slice(8) : target;
  }
  if (step.op === "classify" && step.on === "tiles") return step.into || step.name || step.model || null;
  return null;
}
function recipeGroups(r) {
  const out = [];
  ((r && r.pipeline) || []).forEach((step, i) => { const g = stepGroup(step); if (g && !out.some(x => x.name === g)) out.push({ name: g, index: i, op: step.op }); });
  return out;
}
function groupName(text) { return String(text || "").trim().replace(/[^\w一-鿿-]+/g, "_").replace(/^_+|_+$/g, ""); }
function applyRecipeObject(obj, text) {
  V.applied = obj; V.text = pretty(obj); V.msg = { cls: "ok", text: text };
  toast(text); renderVision();
}
function addClassifyStep() {
  const r = recipe();
  if (!r || !VM.clsModel || !VM.clsGroup) return;
  const obj = JSON.parse(JSON.stringify(r));
  obj.pipeline = (obj.pipeline || []).filter(s => !(s && s.op === "classify" && s.on === "regions:" + VM.clsGroup));
  const at = obj.pipeline.findIndex(s => stepGroup(s) === VM.clsGroup);
  obj.pipeline.splice(at < 0 ? obj.pipeline.length : at + 1, 0, { op: "classify", model: VM.clsModel, on: "regions:" + VM.clsGroup });
  applyRecipeObject(obj, t("vm.added"));
}
function addDetectStep() {
  const r = recipe();
  const group = groupName(VM.detGroup) || groupName(VM.detModel) || "objects";
  if (!r || !VM.detModel) return;
  const conf = Number(VM.detConf);
  const obj = JSON.parse(JSON.stringify(r));
  const step = { op: "detect", model: VM.detModel, conf: isFinite(conf) && conf > 0 && conf < 1 ? conf : 0.4, as: "regions:" + group };
  const pipeline = obj.pipeline || [];
  const at = pipeline.findIndex(s => s && s.op === "detect" && stepGroup(s) === group);
  if (at >= 0) pipeline[at] = step; else pipeline.unshift(step);
  obj.pipeline = pipeline;
  if (VM.detCount) {
    obj.measurements = obj.measurements || {};
    if (!obj.measurements[group + "_count"]) obj.measurements[group + "_count"] = { label: t("vm.countLabel", { g: group }), decimals: 0, compute: { type: "count", regions: group } };
  }
  applyRecipeObject(obj, t("vm.added"));
}
function removeModelStep(index) {
  const r = recipe();
  if (!r) return;
  const obj = JSON.parse(JSON.stringify(r));
  const [step] = obj.pipeline.splice(index, 1);
  const group = step && step.op === "detect" ? stepGroup(step) : null;
  if (group && !obj.pipeline.some(s => stepGroup(s) === group)) {        // 没人再产出这个区域组：把引用它的测量项和 draw 一起去掉，方案才还能跑
    Object.keys(obj.measurements || {}).forEach(k => { const c = obj.measurements[k] && obj.measurements[k].compute; if (c && c.regions === group) delete obj.measurements[k]; });
    if (Array.isArray(obj.draw)) obj.draw = obj.draw.filter(d => !(d && d.regions === group));
    obj.pipeline = obj.pipeline.filter(s => !(s && s.op === "classify" && s.on === "regions:" + group));
  }
  applyRecipeObject(obj, t("vm.removed"));
}
function syncDecisionSelect() {
  const sel = $("#v-dec-model");
  if (!sel) return;
  const current = S.model.trim();
  if (current && !Array.from(sel.options).some(o => o.value === current)) sel.append(h("option", { value: current }, t("pick.other", { id: current })));
  sel.value = current;
}
function stepSummary(step) {
  if (step.op === "classify") return t("vm.stepClassify", { m: step.model, g: String(step.on || "image").replace(/^regions:/, "") });
  return t("vm.stepDetect", { m: step.model || step.model_file, g: stepGroup(step) });
}
function modelsCard() {
  const card = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("vm.title"))));
  const r = recipe();
  /* 决策模型 */
  const dec = h("select", { id: "v-dec-model", class: "inline-input grow", onchange: e => {
    S.model = e.target.value; const box = $("#model"); if (box) box.value = S.model;
    refresh(); renderModelOptions();
  } });
  dec.append(h("option", { value: "" }, t("pick.empty") + (activeModel() ? "  → " + activeModel() : "")));
  modelChoices().forEach(m => dec.append(h("option", { value: m.id }, modelLabel(m))));
  card.append(h("div", { class: "rowline" }, h("span", { class: "hint vm-label" }, t("vm.decision")), dec));
  if (!visionReady()) { card.append(h("div", { class: "hint warn" }, t("v.needVision"))); return card; }
  if (!VM.loaded) { loadVisionModels(); card.append(h("div", { class: "fine" }, t("vm.loading"))); return card; }
  const goTrain = tab => h("button", { class: "btn small", type: "button", onclick: () => { setTrainTab(tab); setView("train"); } }, t("vm.goTrain"));
  const groups = recipeGroups(r);
  /* 区域分类模型 */
  if (!VM.cls.length) card.append(h("div", { class: "rowline" }, h("span", { class: "hint vm-label" }, t("vm.classifier")), h("span", { class: "hint" }, t("vm.noCls")), goTrain("cls")));
  else {
    const clsSel = h("select", { class: "inline-input grow", "aria-label": t("vm.classifier"), onchange: e => { VM.clsModel = e.target.value; } });
    VM.cls.forEach(m => clsSel.append(h("option", { value: m.name }, m.name + "  (" + (m.classes || []).join("/") + ")")));
    clsSel.value = VM.clsModel;
    if (!groups.some(g => g.name === VM.clsGroup)) VM.clsGroup = groups.length ? groups[0].name : "";
    const grpSel = h("select", { class: "inline-input", "aria-label": t("vm.group"), onchange: e => { VM.clsGroup = e.target.value; } });
    groups.forEach(g => grpSel.append(h("option", { value: g.name }, g.name)));
    grpSel.value = VM.clsGroup;
    card.append(h("div", { class: "rowline" }, h("span", { class: "hint vm-label" }, t("vm.classifier")), clsSel, h("span", { class: "hint" }, t("vm.group")),
      groups.length ? grpSel : h("span", { class: "hint warn" }, t("vm.noGroups")),
      h("button", { class: "btn small primary", type: "button", disabled: !r || !groups.length, onclick: addClassifyStep }, t("vm.add"))));
  }
  /* 检测模型 */
  if (!VM.det.length) card.append(h("div", { class: "rowline" }, h("span", { class: "hint vm-label" }, t("vm.detector")), h("span", { class: "hint" }, t("vm.noDet")), goTrain("det")));
  else {
    const detSel = h("select", { class: "inline-input grow", "aria-label": t("vm.detector"), onchange: e => { VM.detModel = e.target.value; if (!VM.touched) VM.detGroup = groupName(VM.detModel); renderVision(); } });
    VM.det.forEach(m => detSel.append(h("option", { value: m.name }, m.name + "  (" + (m.classes || []).join("/") + ")")));
    detSel.value = VM.detModel;
    if (!VM.touched) VM.detGroup = groupName(VM.detModel);
    const grp = h("input", { class: "inline-input", id: "v-det-group", value: VM.detGroup, placeholder: "objects", "aria-label": t("vm.outGroup"), oninput: e => { VM.detGroup = e.target.value; VM.touched = true; } });
    const conf = h("input", { class: "inline-input", type: "number", min: "0.05", max: "0.95", step: "0.05", value: VM.detConf, style: "width:72px", "aria-label": t("vm.conf"), oninput: e => { VM.detConf = e.target.value; } });
    grp.style.width = "130px";
    card.append(h("div", { class: "rowline" }, h("span", { class: "hint vm-label" }, t("vm.detector")), detSel));
    card.append(h("div", { class: "rowline" }, h("span", { class: "vm-label" }), h("span", { class: "hint" }, t("vm.outGroup")), grp, h("span", { class: "hint" }, t("vm.conf")), conf));
    card.append(h("div", { class: "rowline" }, h("span", { class: "vm-label" }), h("label", { class: "check" }, h("input", { type: "checkbox", checked: VM.detCount || null, onchange: e => { VM.detCount = e.target.checked; } }), t("vm.addCount")),
      h("span", { class: "spacer" }), h("button", { class: "btn small primary", type: "button", disabled: !r, onclick: addDetectStep }, t("vm.add"))));
  }
  /* 方案里已有的模型步骤 */
  const steps = ((r && r.pipeline) || []).map((s, i) => [s, i]).filter(p => p[0] && (p[0].op === "classify" || p[0].op === "detect"));
  if (steps.length) {
    const list = h("div", { class: "fine" }, t("vm.inRecipe"));
    steps.forEach(([step, i]) => list.append(h("div", { class: "rowline", style: "margin:4px 0 0" }, h("code", {}, stepSummary(step)),
      h("button", { class: "btn small", type: "button", onclick: () => removeModelStep(i) }, t("vm.remove")))));
    card.append(list);
  }
  card.append(h("p", { class: "fine", style: "margin-bottom:0" }, t("vm.note")));
  return card;
}

/* ---------- 渲染：视觉检测 ---------- */
function renderVision() {
  const root = $("#vision-root");
  if (!root || S.view !== "vision") return;
  const keepFocus = document.activeElement && document.activeElement.id;
  const keepScroll = $("#v-recipe-json") ? $("#v-recipe-json").scrollTop : 0;
  root.textContent = "";

  /* 方案 */
  const top = h("section", { class: "card intro" }, statusLine());
  const buttons = h("div", { class: "examples" }, h("span", { class: "label" }, t("v.recipes")));
  V.recipes.forEach(item => buttons.append(h("button", { class: "btn" + (item.id === V.recipeId ? " on" : ""), type: "button", title: item.note,
    onclick: () => { stopCamera(); selectRecipe(item.id); renderVision(); } }, item.title + (item.custom ? t("v.custom") : ""))));
  if (V.loaded && !V.recipes.length) buttons.append(h("span", { class: "hint" }, t("v.noRecipes")));
  top.append(buttons);
  const item = recipeItem();
  top.append(h("p", { class: "vnote" }, item ? item.note + (V.applied ? "　·　" + t("v.edited") : "") : ""));
  if (item && item.problems && item.problems.length) top.append(h("div", { class: "errbox" }, item.problems.join("\n")));
  root.append(top);

  const grid = h("main", { class: "grid" });
  const left = h("div", { class: "col" });
  const r = recipe();

  /* 图像 */
  const imgCard = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("v.image"))));
  const fileInput = h("input", { type: "file", accept: "image/*", hidden: true, onchange: e => { const f = e.target.files[0]; e.target.value = ""; useFile(f); } });
  imgCard.append(fileInput);
  const annotated = V.last && V.last.analysis && V.last.analysis.annotated;
  if (V.camera) {
    const video = h("video", { id: "v-video", autoplay: true, playsinline: true, muted: true });
    video.srcObject = V.camera;
    imgCard.append(h("div", { class: "imgbox" }, video));
  } else if (V.image) {
    imgCard.append(h("div", { class: "imgbox" }, h("img", { src: annotated && V.showAnnotated ? annotated : V.image, alt: "" })));
    if (annotated && V.showAnnotated && V.last.analysis.legend && V.last.analysis.legend.length) {
      const legend = h("div", { class: "legend" });
      V.last.analysis.legend.forEach(l => { const sw = h("i"); sw.style.background = l.color; legend.append(h("span", {}, sw, l.label)); });
      imgCard.append(legend);
    }
  } else {
    const drop = h("div", { class: "drop", role: "button", tabindex: "0", onclick: () => fileInput.click(),
      onkeydown: e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } } }, t("v.drop"), h("small", {}, t("v.dropSmall")));
    imgCard.append(drop);
  }
  imgCard.addEventListener("dragover", e => { e.preventDefault(); const d = $(".drop", imgCard); if (d) d.classList.add("over"); });
  imgCard.addEventListener("dragleave", () => { const d = $(".drop", imgCard); if (d) d.classList.remove("over"); });
  imgCard.addEventListener("drop", e => { e.preventDefault(); const f = imageFiles(e.dataTransfer.files)[0]; if (f) useFile(f); });
  const bar = h("div", { class: "imgbar" });
  if (V.camera) {
    bar.append(h("button", { class: "btn primary", type: "button", onclick: shoot }, t("v.shoot")),
      h("button", { class: "btn", type: "button", onclick: () => { stopCamera(); renderVision(); } }, t("v.cancel")));
  } else {
    bar.append(h("button", { class: "btn", type: "button", onclick: () => fileInput.click() }, t("v.pick")));
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) bar.append(h("button", { class: "btn", type: "button", onclick: startCamera }, t("v.camera")));
    if (r && r.demo && r.demo.scene) {
      bar.append(h("span", { class: "sep" }), h("span", { class: "hint", title: t("v.demoNote") }, t("v.demo")));
      (r.demo.variants || []).forEach(name => bar.append(h("button", { class: "btn small", type: "button", disabled: !visionReady(), title: t("v.demoNote"),
        onclick: () => useDemo(r.demo.scene, name) }, I18N[LANG]["demo." + name] ? t("demo." + name) : name)));
    }
    if (annotated) bar.append(h("span", { class: "spacer" }), h("button", { class: "btn small", type: "button",
      onclick: () => { V.showAnnotated = !V.showAnnotated; renderVision(); } }, V.showAnnotated ? t("v.showOriginal") : t("v.showAnnotated")));
  }
  imgCard.append(bar);
  left.append(imgCard);

  /* 补充信息 */
  left.append(h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("v.context"))),
    h("textarea", { id: "v-context", value: V.context, placeholder: t("v.contextPh"), oninput: e => { V.context = e.target.value; } })));

  /* 运行 */
  const problem = runProblem();
  left.append(h("section", { class: "card runbar" },
    h("button", { class: "run", id: "v-run", type: "button", disabled: V.running || !!problem, onclick: runInspect },
      h("span", { "aria-hidden": "true" }, "▷"), h("span", {}, V.running ? t("v.running") : t("v.run"))),
    h("label", { class: "check" }, h("input", { type: "checkbox", checked: V.rulesOnly || null, onchange: e => { V.rulesOnly = e.target.checked; } }), t("v.rulesOnly")),
    h("span", { class: "hint warn" }, V.running ? "" : problem)));

  /* 模型 */
  left.append(modelsCard());

  /* 方案内容 */
  const fold = h("details", { class: "fold", id: "v-fold" }, h("summary", {}, t("v.recipeJson")));
  if (renderVision.foldOpen) fold.open = true;
  fold.addEventListener("toggle", () => { renderVision.foldOpen = fold.open; });
  fold.append(h("textarea", { id: "v-recipe-json", value: V.text, spellcheck: "false", oninput: e => { V.text = e.target.value; } }));
  const acts = h("div", { class: "set-actions" },
    h("button", { class: "btn small primary", type: "button", onclick: applyRecipeText }, t("v.apply")),
    h("button", { class: "btn small", type: "button", onclick: () => { selectRecipe(V.recipeId); renderVision(); } }, t("v.revert")),
    h("button", { class: "btn small", type: "button", onclick: async () => {
      let obj;
      try { obj = JSON.parse(V.text); } catch (e) { V.msg = { cls: "bad", text: t("v.badJson", { msg: e.message }) }; return renderVision(); }
      const res = await jpost("/_wb/recipes/save", { recipe: obj, title: (item ? item.title : obj.id) + "", note: item ? item.note : "" });
      if (!res.ok) { V.msg = { cls: "bad", text: errText(res) }; return renderVision(); }
      V.recipes = res.data.recipes; selectRecipe(res.data.id); V.msg = { cls: "ok", text: t("v.saved", { id: res.data.id }) }; renderVision();
    } }, t("v.saveAs")));
  if (item && item.custom) acts.append(h("span", { class: "spacer" }), h("button", { class: "btn small danger", type: "button", onclick: async () => {
    const res = await jpost("/_wb/recipes/delete", { file: item.file });
    if (!res.ok) { V.msg = { cls: "bad", text: errText(res) }; return renderVision(); }
    V.recipes = res.data.recipes; selectRecipe(V.recipes.length ? V.recipes[0].id : null); toast(t("v.deleted")); renderVision();
  } }, t("v.delete")));
  fold.append(acts, h("div", { class: "prov-msg " + ((V.msg && V.msg.cls) || "") }, (V.msg && V.msg.text) || ""));
  left.append(h("section", { class: "card" }, fold));

  grid.append(left);
  const right = h("section", { class: "card" });
  const tabs = h("div", { class: "tabs", role: "tablist" });
  ["verdict", "measure", "state", "raw", "selftest"].forEach(name => tabs.append(h("button", { type: "button", role: "tab",
    "aria-selected": String(V.tab === name), onclick: () => { V.tab = name; renderResult(); } }, t("v.tab." + name))));
  right.append(tabs, h("div", { id: "v-panel" }));
  grid.append(right);
  root.append(grid);
  renderResult();
  syncDecisionSelect();
  if (keepFocus) { const el = document.getElementById(keepFocus); if (el && (el.tagName === "TEXTAREA" || el.id === "v-det-group")) { el.focus(); if (el.setSelectionRange && el.id === "v-det-group") el.setSelectionRange(el.value.length, el.value.length); } }
  if ($("#v-recipe-json")) $("#v-recipe-json").scrollTop = keepScroll;
}

function valueOptions(spec) {
  if (spec.type === "choice") {
    const keys = Array.isArray(spec.criteria) ? spec.criteria.map(String) : Object.keys(spec.criteria || {});
    return keys.map(k => [k, k]);
  }
  if (spec.type === "score") return (spec.criteria || []).map((text, i) => [String(i), i + " · " + text]);
  return [["true", t("v.yes")], ["false", t("v.no")]];
}
function verdictCard(qid, v, spec) {
  const card = h("div", { class: "ans" + (v.review ? " low" : "") });
  const head = h("div", { class: "ans-head" }, h("span", { class: "badge " + v.type }, t("type." + v.type)), h("code", {}, qid),
    h("span", { class: "src" + (v.source === "rule" ? " rule" : "") }, t("v.src." + (v.source === "rule" ? "rule" : v.source === "model" ? "model" : "none"))));
  if (v.agree === true) head.append(h("span", { class: "flag good" }, t("v.agree")));
  if (v.agree === false) head.append(h("span", { class: "flag bad" }, t("v.conflict")));
  if (v.rule && v.rule.marginal) head.append(h("span", { class: "flag" }, t("v.flag.edge")));
  if (v.review) head.append(h("span", { class: "flag" }, t("v.flag.review")));
  card.append(head);
  card.append(h("div", { class: "ans-q" }, (spec && spec.instructions ? spec.instructions : v.instructions).split("\n")[0]));
  const crit = spec && spec.criteria && !Array.isArray(spec.criteria) ? spec.criteria : {};
  card.append(h("div", { class: "verdict" }, h("strong", {}, v.final_text), v.type === "choice" && crit[v.final] ? h("span", {}, crit[v.final]) : null));

  const cmp = h("dl", { class: "cmp" });
  if (v.rule) {
    cmp.append(h("dt", {}, t("v.rule")), h("dd", {}, v.rule.result_text, h("br"), h("small", {}, v.rule.text)));
    cmp.append(h("dt", {}, t("v.standard")), h("dd", {}, h("small", {}, v.rule.standard)));
  }
  if (v.model) {
    cmp.append(h("dt", {}, t("v.model")), h("dd", {}, v.model.result_text + (v.model.confidence != null ? "　" + t("v.conf", { v: Number(v.model.confidence).toFixed(3) }) : "") +
      (v.model.low_confidence ? "　" + t("r.lowConf") : "")));
  } else if (V.last && V.last.use_model) cmp.append(h("dt", {}, t("v.model")), h("dd", {}, t("v.noModelAnswer")));
  if (cmp.children.length) card.append(cmp);
  if (v.model && v.model.answer && v.source === "model") {            // 结论来自模型时，把概率分布画出来
    const a = v.model.answer;
    if (v.type === "choice" && a.probabilities) Object.keys(a.probabilities).forEach(k => card.append(barRow(k, a.probabilities[k], k === a.choice)));
    else if (v.type === "score" && a.probabilities) Object.keys(a.probabilities).forEach(k => card.append(barRow(k + "  " + ((a.legend || {})[k] || ""), a.probabilities[k], k === String(Math.round(Number(a.score))))));
    else if (a.noul != null) card.append(barRow(t("r.yes"), a.noul, Number(a.noul) >= 0.5, true));
  }
  if (v.reasons && v.reasons.length) card.append(h("div", { class: "conf" }, v.reasons.join(t("sep.semi"))));

  if (spec) {
    const select = h("select", { "aria-label": t("v.reviewPick"), onchange: e => { V.reviewPick[qid] = e.target.value; } });
    valueOptions(spec).forEach(o => select.append(h("option", { value: o[0] }, o[1])));
    if (V.reviewPick[qid] != null) select.value = V.reviewPick[qid];
    else if (v.final != null) select.value = String(v.final);
    card.append(h("div", { class: "review-row" }, t("v.reviewPick"), select,
      h("button", { class: "btn small", type: "button", onclick: () => {
        const raw = select.value;
        saveReview(qid, v.type === "noul" ? raw === "true" : v.type === "score" ? Number(raw) : raw);
      } }, t("v.reviewSave")), V.reviewMsg[qid] ? h("span", {}, V.reviewMsg[qid]) : null));
  }
  return card;
}
function fmtNum(x, digits) { return x == null ? "-" : Number(x).toFixed(digits == null ? 1 : digits).replace(/\.0+$/, ""); }

function renderResult() {
  const panel = $("#v-panel");
  if (!panel) return;
  panel.textContent = "";
  panel.parentElement.querySelectorAll(".tabs button").forEach((b, i) => b.setAttribute("aria-selected", String(["verdict", "measure", "state", "raw", "selftest"][i] === V.tab)));
  if (V.tab === "selftest") return renderSelftest(panel);
  if (V.running) { panel.append(h("div", { class: "placeholder" }, t("v.running"))); return; }
  if (V.error) { panel.append(h("div", { class: "errbox" }, t("v.fail") + "\n" + V.error)); return; }
  const run = V.last;
  if (!run) { panel.append(h("div", { class: "placeholder" }, t("v.empty"))); return; }
  const r = recipe() || {};

  if (V.tab === "verdict") {
    const modelDown = run.use_model && run.model && !run.model.ok;
    const banner = h("div", { class: "banner " + (run.review ? "review" : "ok") }, run.review ? t("v.review") : (run.use_model && !modelDown ? t("v.pass") : t("v.passRules")));
    if (run.reasons && run.reasons.length) { const ul = h("ul"); run.reasons.forEach(x => ul.append(h("li", {}, x))); banner.append(ul); }
    panel.append(banner);
    if (modelDown) panel.append(h("div", { class: "banner info" }, t("v.modelDown", { msg: run.model.error || "" })));
    (run.missing_models || []).forEach(name => {
      const box = h("div", { class: "banner info" }, t("v.missingModel", { name: name }));
      if (r.train && r.train.model === name) box.append(h("br"), h("button", { class: "btn small", type: "button", disabled: V.preparing, onclick: prepareModel }, t("v.prepare")));
      panel.append(box);
    });
    (run.missing_files || []).forEach(name => panel.append(h("div", { class: "banner info" }, t("v.missingFile", { name: name }))));
    if (V.prepareMsg) panel.append(h("div", { class: "prov-msg " + (V.prepareMsg.cls || "") }, V.prepareMsg.text));
    const ids = Object.keys(run.verdicts || {});
    ids.forEach(qid => panel.append(verdictCard(qid, run.verdicts[qid], (run.questions || {})[qid])));
    const a = run.analysis;
    const parts = [];
    if (a) parts.push(run.model ? t("v.timing", { a: fmtNum(a.ms, 0), b: fmtNum(run.model.ms, 0), c: fmtNum(run.ms, 0) }) : t("v.timingRules", { a: fmtNum(a.ms, 0), c: fmtNum(run.ms, 0) }));
    if (run.model && run.model.ok) parts.push(t("m.iface", { v: run.model.provider === "local" ? t("t.local") : (pname(providerById(run.model.provider)) || run.model.provider) }) + (run.model.model ? t("sep.gap") + t("m.model", { v: run.model.model }) : ""));
    if (parts.length) panel.append(h("div", { class: "conf" }, parts.join(t("sep.gap"))));
    return;
  }

  if (V.tab === "measure") {
    const q = run.quality || {};
    panel.append(h("div", { class: "fine" }, t("v.quality") + t("sep.colon") + (q.ok === false ? (q.problems || []).join(t("sep.semi")) : t("v.qualityOk", { s: fmtNum(q.sharpness, 0), b: fmtNum(q.brightness, 0) }))));
    const table = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("v.th.item")), h("th", {}, t("v.th.value")))));
    const body = h("tbody");
    (run.measures || []).forEach(m => { if (m.value != null) body.append(h("tr", {}, h("td", {}, m.label), h("td", {}, m.text))); });
    table.append(body);
    panel.append(h("div", { class: "table-wrap" }, table));
    const regions = (run.analysis && run.analysis.regions) || {};
    const unit = run.analysis && run.analysis.mm_per_px ? ["mm²", "mm"] : ["px²", "px"];
    Object.keys(regions).forEach(group => {
      const rows = regions[group];
      if (!rows.length) return;
      const shown = rows.slice(0, 40);
      panel.append(h("div", { class: "sub" }, t("v.regions", { name: group }), h("small", {}, t("v.regionsCount", { n: rows.length }) + (rows.length > shown.length ? t("sep.gap") + t("v.regionsMore", { n: shown.length }) : ""))));
      const hasLabel = rows.some(x => x.label);
      const tb = h("tbody");
      shown.forEach(x => {
        const key = group + ":" + x.id;
        tb.append(h("tr", {}, h("td", {}, h("input", { type: "checkbox", checked: V.picked[key] || null, "aria-label": "#" + x.id, onchange: e => { V.picked[key] = e.target.checked; } })),
          h("td", { class: "num" }, String(x.id)), hasLabel ? h("td", {}, (x.label || "-") + (x.prob != null ? "  " + pct(x.prob) : "")) : null,
          h("td", { class: "num" }, fmtNum(x.area, 1)), h("td", { class: "num" }, fmtNum(x.length, 1)), h("td", { class: "num" }, fmtNum(x.width, 1)), h("td", { class: "num" }, fmtNum(x.elongation, 1))));
      });
      panel.append(h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", { class: "num" }, t("v.th.id")),
        hasLabel ? h("th", {}, t("v.th.label")) : null, h("th", { class: "num" }, t("v.th.area") + " " + unit[0]), h("th", { class: "num" }, t("v.th.length") + " " + unit[1]),
        h("th", { class: "num" }, t("v.th.width") + " " + unit[1]), h("th", { class: "num" }, t("v.th.elong")))), tb)));
      const list = h("datalist", { id: "v-ds-list" });
      TR.datasets.forEach(d => list.append(h("option", { value: d.name })));
      panel.append(h("div", { class: "rowline", style: "margin-top:10px" }, h("span", { class: "hint" }, t("v.addSel")),
        h("input", { class: "inline-input", list: "v-ds-list", placeholder: t("v.addDataset"), value: V.addDataset, oninput: e => { V.addDataset = e.target.value; } }), list,
        h("input", { class: "inline-input", placeholder: t("v.addLabel"), value: V.addLabel, oninput: e => { V.addLabel = e.target.value; } }),
        h("button", { class: "btn small", type: "button", onclick: () => addRegions(group) }, t("v.addBtn"))));
    });
    return;
  }

  if (V.tab === "state") {
    const body = { state: run.state, questions: run.questions };
    if (S.model.trim()) body.model = S.model.trim();
    const text = pretty(body);
    panel.append(h("p", { class: "fine" }, t("v.stateNote")));
    panel.append(h("div", { class: "tools" }, h("button", { class: "btn small", type: "button", onclick: () => copyText(text) }, t("v.copy")),
      h("button", { class: "btn small", type: "button", onclick: () => { try { loadRequest(body); S.last = null; S.note = ""; setView("text"); refresh(); renderPanel(); } catch (e) { toast(e.message); } } }, t("v.openText"))));
    panel.append(h("pre", { class: "code" }, text));
    return;
  }

  const slim = JSON.parse(JSON.stringify(run));
  if (slim.analysis && slim.analysis.annotated) slim.analysis.annotated = "(data URL, " + run.analysis.annotated.length + " chars)";
  const text = pretty(slim);
  panel.append(h("div", { class: "tools" }, h("button", { class: "btn small", type: "button", onclick: () => copyText(text) }, t("v.copy"))));
  panel.append(h("pre", { class: "code" }, text));
}

function renderSelftest(panel) {
  const r = recipe() || {};
  const bound = Object.keys(r.bindings || {}).filter(q => (r.questions || {})[q]);
  panel.append(h("p", { class: "fine" }, t("v.st.intro")));
  if (!bound.length) { panel.append(h("div", { class: "banner info" }, t("v.st.none"))); return; }
  panel.append(h("div", { class: "tools" },
    h("button", { class: "btn primary", type: "button", disabled: V.selfRunning, onclick: runSelftest }, V.selfRunning ? t("v.st.running") : t("v.st.run")),
    h("span", { class: "hint" }, t("v.st.cost", { n: 96 }))));
  if (V.selfError) panel.append(h("div", { class: "errbox" }, t("v.st.fail", { msg: V.selfError })));
  const rep = V.selftest[V.recipeId];
  if (!rep || !rep.levels) { panel.append(h("div", { class: "fine" }, t("v.st.never"))); }
  else {
    panel.append(h("div", { class: "fine" }, t("v.st.last", { time: rep.time, n: rep.cases, model: rep.model || "-" })));
    const cell = (row, key) => { const x = row && row[key]; return h("td", { class: "num " + (x == null ? "" : x >= rep.threshold ? "ok" : x >= 0.9 ? "edge" : "no") }, x == null ? "-" : pct(x)); };
    const tb = h("tbody");
    Object.keys(rep.advice || {}).forEach(qid => {
      const raw = (rep.levels.raw || {})[qid], cmp = (rep.levels.compared || {})[qid];
      tb.append(h("tr", {}, h("td", {}, h("code", {}, qid)), cell(raw, "accuracy"), cell(cmp, "accuracy"), cell(cmp, "near_accuracy"),
        h("td", { class: rep.advice[qid] === "advise" ? "ok" : "edge" }, t("v.st." + (rep.advice[qid] === "advise" ? "advise" : "enforce")))));
    });
    panel.append(h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("v.st.th.q")), h("th", { class: "num" }, t("v.st.th.raw")),
      h("th", { class: "num" }, t("v.st.th.cmp")), h("th", { class: "num" }, t("v.st.th.near")), h("th", {}, t("v.st.th.advice")))), tb)));
    panel.append(h("p", { class: "fine" }, t("v.st.explain", { th: pct(rep.threshold) })));
    const misses = [];
    Object.keys(rep.levels.compared || {}).forEach(qid => (rep.levels.compared[qid].misses || []).forEach(m => misses.push([qid, m])));
    if (misses.length) {
      panel.append(h("div", { class: "sub" }, t("v.st.misses")));
      const specs = r.measurements || {};
      misses.slice(0, 8).forEach(pair => {
        const vals = Object.keys(pair[1].values).map(k => ((specs[k] && specs[k].label) || k) + " " + pair[1].values[k]).join(t("sep.list"));
        panel.append(h("div", { class: "fine" }, h("code", {}, pair[0]), "　" + vals + "　→　" + t("v.st.expected", { a: String(pair[1].expected), b: String(pair[1].got) })));
      });
    }
  }
  panel.append(h("div", { class: "tools", style: "margin-top:14px" },
    h("a", { class: "btn small", href: "/v1/inspect/export?recipe=" + encodeURIComponent(V.recipeId), download: "" }, t("v.export")),
    h("span", { class: "hint" }, t("v.exportNote"))));
}

/* ---------- 训练 ---------- */
async function loadTrain() {
  if (!visionReady()) { TR.loaded = false; return renderTrain(); }
  const [a, b] = await Promise.all([jget("/v1/vision/datasets"), jget("/v1/vision/models")]);
  TR.datasets = a.ok ? a.data.datasets : [];
  TR.models = b.ok ? b.data.models : [];
  TR.loaded = true;
  if (!TR.datasets.some(d => d.name === TR.dataset)) TR.dataset = TR.datasets.length ? TR.datasets[0].name : "";
  if (!TR.form.name) TR.form.name = TR.dataset;
  renderTrain();
}
async function uploadImages(dataset, label, files) {
  files = imageFiles(files);
  if (!files.length) return;
  let done = 0, saved = 0;
  for (let i = 0; i < files.length; i += 6) {
    TR.upload = t("t.uploading", { a: done, b: files.length }); renderTrain();
    const chunk = await Promise.all(files.slice(i, i + 6).map(f => fileToDataUrl(f, 1280).catch(() => null)));
    const res = await jpost("/v1/vision/datasets/add", { dataset: dataset, label: label, images: chunk.filter(Boolean) });
    if (!res.ok) { TR.upload = ""; toast(errText(res)); return loadTrain(); }
    saved += res.data.saved; done += chunk.length;
  }
  TR.upload = ""; TR.dataset = dataset; toast(t("t.uploaded", { n: saved }));
  loadTrain();
}
async function trainJob(kind, path, body, onDone) {
  if (TR.job) return;
  TR.msg = null; TR.jobKind = kind;
  const res = await jpost(path, body);
  if (!res.ok) { TR.msg = { cls: "bad", text: errText(res) }; return renderTrain(); }
  TR.job = res.data; renderTrain();
  const job = await pollJob(TR.job, cur => { TR.job = cur; renderTrain.progress(); });
  TR.job = null;
  if (job.state === "done") onDone(job.result); else TR.msg = { cls: "bad", text: t("t.fail", { msg: job.error || "" }) };
  VM.loaded = false;
  loadTrain();
}
function startTrain() {
  const f = TR.form;
  const bb = vision() && vision().health && vision().health.backbone;
  if (!TR.dataset) { TR.msg = { cls: "bad", text: t("t.needDataset") }; return renderTrain(); }
  if (!f.name.trim()) { TR.msg = { cls: "bad", text: t("t.needName") }; return renderTrain(); }
  if (f.features.includes("deep") && !(bb && bb.available)) { TR.msg = { cls: "bad", text: t("t.needDeep") }; return renderTrain(); }
  trainJob("train", "/v1/vision/train", { dataset: TR.dataset, name: f.name.trim(), features: f.features, algo: f.algo, augment: f.augment, rotate: f.rotate },
    result => { TR.result = result; });
}
async function downloadBackbone() {
  if (TR.bbJob) return;
  const res = await jpost("/v1/vision/backbone/download", {});
  if (!res.ok) { TR.bbMsg = { cls: "bad", text: errText(res) }; return renderTrain(); }
  TR.bbJob = res.data; TR.bbMsg = null; renderTrain();
  const job = await pollJob(TR.bbJob, cur => { TR.bbJob = cur; const el = $("#t-bb-progress"); if (el) el.textContent = t("t.bbDownloading", { p: Math.round((cur.progress || 0) * 100) + "%" }); });
  TR.bbJob = null;
  TR.bbMsg = job.state === "done" ? { cls: "ok", text: t("t.bbDone") } : { cls: "bad", text: t("t.bbFail", { msg: job.error || "" }) };
  pollStatus();
}

function renderTrain() {
  const root = $("#train-root");
  if (!root || S.view !== "train") return;
  root.textContent = "";
  const health = visionReady() ? vision().health : null;
  const bb = health && health.backbone;

  const top = h("section", { class: "card intro" }, statusLine());
  if (health) {
    top.append(h("div", { class: "vstatus" }, h("span", { class: "dot " + (bb && bb.available ? "ok" : "") }), t("t.backbone") + t("sep.colon") +
      (bb && bb.available ? t("t.bbReady", { file: bb.file, dim: bb.dim }) : bb && bb.error ? t("t.bbBad", { msg: bb.error }) : t("t.bbMissing")),
      bb && bb.available ? null : h("button", { class: "btn small", type: "button", disabled: !!TR.bbJob, onclick: downloadBackbone }, t("t.bbDownload")),
      TR.bbJob ? h("span", { class: "hint", id: "t-bb-progress" }, t("t.bbDownloading", { p: Math.round((TR.bbJob.progress || 0) * 100) + "%" })) : null));
    if (TR.bbMsg) top.append(h("div", { class: "prov-msg " + TR.bbMsg.cls }, TR.bbMsg.text));
    top.append(h("p", { class: "fine", style: "margin-bottom:0" }, t("t.bbNote")));
  }
  root.append(top);
  if (!health) return;
  const seg = h("div", { class: "seg", role: "group", style: "margin-bottom:14px" });
  [["cls", "det.tab.cls"], ["det", "det.tab.det"]].forEach(pair => seg.append(h("button", { type: "button", "aria-pressed": String(DT.tab === pair[0]), onclick: () => setTrainTab(pair[0]) }, t(pair[1]))));
  root.append(seg);
  if (DT.tab === "det") return renderDetect(root, health);
  if (!TR.loaded) { loadTrain(); return; }

  const grid = h("main", { class: "grid" });

  /* 数据集 */
  const dsCard = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("t.datasets"))));
  const select = h("select", { class: "inline-input grow", "aria-label": t("t.dataset"), onchange: e => { TR.dataset = e.target.value; TR.form.name = TR.dataset; TR.confirm = ""; renderTrain(); } });
  TR.datasets.forEach(d => select.append(h("option", { value: d.name }, d.name + "  (" + d.total + ")")));
  select.value = TR.dataset;
  const newName = h("input", { class: "inline-input grow", placeholder: t("t.newDataset") });
  dsCard.append(h("div", { class: "rowline" }, TR.datasets.length ? select : null, newName,
    h("button", { class: "btn small", type: "button", onclick: () => {
      const name = newName.value.trim();
      if (!name) return toast(t("t.needName"));
      if (!TR.datasets.some(d => d.name === name)) TR.datasets.push({ name: name, classes: [], total: 0 });
      TR.dataset = name; TR.form.name = name; renderTrain();
    } }, t("t.create"))));
  const scene = h("select", { class: "inline-input", "aria-label": t("t.demoScene"), onchange: e => { TR.scene = e.target.value; } });
  Object.keys(health.scenes || {}).forEach(name => scene.append(h("option", { value: name }, name)));
  scene.value = TR.scene;
  dsCard.append(h("div", { class: "rowline" }, h("span", { class: "hint" }, t("t.demoGen")), scene,
    h("button", { class: "btn small", type: "button", disabled: !!TR.job, onclick: () => trainJob("dataset", "/v1/vision/datasets/demo", { scene: TR.scene },
      result => { TR.dataset = result.dataset; TR.form.name = result.dataset; TR.msg = { cls: "ok", text: t("t.generated", { name: result.dataset }) + (LANG === "en" ? " " : "") + t("t.synthNote") }; }) }, t("t.demoGen"))));

  const ds = TR.datasets.find(d => d.name === TR.dataset);
  if (!ds) dsCard.append(h("div", { class: "empty" }, t("t.noDataset")));
  else {
    ds.classes.forEach(c => {
      const picker = h("input", { type: "file", accept: "image/*", multiple: true, hidden: true, onchange: e => { const fs = Array.from(e.target.files); e.target.value = ""; uploadImages(ds.name, c.label, fs); } });
      const box = h("div", { class: "cls" }, picker, h("div", { class: "cls-head" }, h("strong", {}, c.label), h("span", { class: "n" }, t("t.count", { n: c.count })), h("span", { class: "spacer" }),
        h("button", { class: "btn small", type: "button", onclick: () => picker.click() }, t("t.addImages")),
        TR.confirm === "c:" + c.label
          ? h("button", { class: "btn small danger", type: "button", onclick: async () => { TR.confirm = ""; await jpost("/v1/vision/datasets/delete", { dataset: ds.name, label: c.label }); loadTrain(); } }, t("t.confirm"))
          : h("button", { class: "btn small danger", type: "button", onclick: () => { TR.confirm = "c:" + c.label; renderTrain(); } }, t("t.delClass"))));
      const thumbs = h("div", { class: "thumbs" });
      c.files.slice(0, 14).forEach(f => thumbs.append(h("img", { loading: "lazy", alt: "", src: "/v1/vision/datasets/thumb?dataset=" + encodeURIComponent(ds.name) + "&label=" + encodeURIComponent(c.label) + "&file=" + encodeURIComponent(f) })));
      box.append(thumbs);
      box.addEventListener("dragover", e => { e.preventDefault(); box.classList.add("over"); });
      box.addEventListener("dragleave", () => box.classList.remove("over"));
      box.addEventListener("drop", e => { e.preventDefault(); box.classList.remove("over"); uploadImages(ds.name, c.label, e.dataTransfer.files); });
      dsCard.append(box);
    });
    const classPicker = h("input", { type: "file", accept: "image/*", multiple: true, hidden: true });
    const className = h("input", { class: "inline-input grow", placeholder: t("t.addClass") });
    classPicker.addEventListener("change", e => { const fs = Array.from(e.target.files); e.target.value = ""; uploadImages(ds.name, className.value.trim(), fs); });
    dsCard.append(classPicker, h("div", { class: "rowline" }, className,
      h("button", { class: "btn small", type: "button", onclick: () => { if (!className.value.trim()) return toast(t("t.needName")); classPicker.click(); } }, t("t.addClassBtn"))));
    dsCard.append(h("div", { class: "rowline" }, h("span", { class: "hint grow" }, TR.upload || t("t.dropHere")),
      ds.total ? (TR.confirm === "d"
        ? h("button", { class: "btn small danger", type: "button", onclick: async () => { TR.confirm = ""; await jpost("/v1/vision/datasets/delete", { dataset: ds.name }); loadTrain(); } }, t("t.confirm"))
        : h("button", { class: "btn small danger", type: "button", onclick: () => { TR.confirm = "d"; renderTrain(); } }, t("t.delDataset"))) : null));
  }
  dsCard.append(h("p", { class: "fine" }, t("t.advice")));
  grid.append(h("div", { class: "col" }, dsCard));

  /* 训练 */
  const f = TR.form;
  const trCard = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("t.train"))));
  trCard.append(h("div", { class: "vfield" }, h("label", { for: "t-name" }, t("t.modelName")), h("input", { id: "t-name", type: "text", value: f.name, oninput: e => { f.name = e.target.value; } })));
  const feats = h("div", { class: "checks" });
  (health.features || []).forEach(name => {
    const off = name === "deep" && !(bb && bb.available);
    feats.append(h("label", { class: "check", title: off ? t("t.needDeep") : "" }, h("input", { type: "checkbox", checked: f.features.includes(name) || null, disabled: off,
      onchange: e => { f.features = e.target.checked ? f.features.concat(name) : f.features.filter(x => x !== name); } }), t("t.f." + name)));
  });
  trCard.append(h("div", { class: "vfield" }, h("label", {}, t("t.features")), feats));
  const algo = h("select", { id: "t-algo", onchange: e => { f.algo = e.target.value; } });
  (health.algos || []).forEach(name => algo.append(h("option", { value: name }, t("t.a." + name))));
  algo.value = f.algo;
  trCard.append(h("div", { class: "vfield" }, h("label", { for: "t-algo" }, t("t.algo")), algo));
  trCard.append(h("div", { class: "checks", style: "margin-bottom:12px" },
    h("label", { class: "check" }, h("input", { type: "checkbox", checked: f.augment || null, onchange: e => { f.augment = e.target.checked; } }), t("t.augment")),
    h("label", { class: "check" }, h("input", { type: "checkbox", checked: f.rotate || null, onchange: e => { f.rotate = e.target.checked; } }), t("t.rotate"))));
  trCard.append(h("div", { class: "rowline" }, h("button", { class: "btn primary", type: "button", disabled: !!TR.job || !health.has_ml, onclick: startTrain }, TR.job && TR.jobKind === "train" ? t("t.training") : t("t.start")),
    h("span", { class: "hint", id: "t-job-text" })));
  trCard.append(h("div", { class: "progress", id: "t-job-bar", hidden: !TR.job }, h("i")));
  if (TR.msg) trCard.append(h("div", { class: "prov-msg " + TR.msg.cls }, TR.msg.text));

  const res = TR.result;
  if (res && res.metrics) {
    const m = res.metrics;
    trCard.append(h("div", { class: "sub" }, t("t.result"), h("small", {}, res.name)));
    trCard.append(h("div", { class: "acc" }, pct(m.accuracy), h("small", {}, t("t.acc"))));
    trCard.append(h("p", { class: "fine" }, t("t.accNote", { k: res.folds, n: res.samples, s: res.seconds })));
    const tb = h("tbody");
    m.per_class.forEach(c => tb.append(h("tr", {}, h("td", {}, c.label), h("td", { class: "num" }, String(c.n)),
      h("td", { class: "num" }, c.recall == null ? "-" : pct(c.recall)), h("td", { class: "num" }, c.precision == null ? "-" : pct(c.precision)))));
    trCard.append(h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("t.th.class")), h("th", { class: "num" }, t("t.th.n")),
      h("th", { class: "num" }, t("t.th.recall")), h("th", { class: "num" }, t("t.th.precision")))), tb)));
    trCard.append(h("div", { class: "sub" }, t("t.cm")));
    const cm = h("table", { class: "cm" }, h("thead", {}, h("tr", {}, h("th", {}, ""), ...res.classes.map(c => h("th", {}, c)))));
    const cb = h("tbody");
    m.confusion.forEach((row, i) => {
      const total = row.reduce((a, b) => a + b, 0) || 1;
      const tr = h("tr", {}, h("th", {}, res.classes[i]));
      row.forEach((n, j) => {
        const td = h("td", { class: i === j ? "diag" : "" }, String(n));
        if (n) td.style.background = i === j ? "rgba(20,184,166," + (0.12 + 0.5 * n / total).toFixed(2) + ")" : "rgba(208,72,72," + (0.12 + 0.6 * n / total).toFixed(2) + ")";
        tr.append(td);
      });
      cb.append(tr);
    });
    cm.append(cb);
    trCard.append(h("div", { class: "table-wrap" }, cm));
  }

  /* 模型 */
  const mdCard = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("t.models"))));
  if (!TR.models.length) mdCard.append(h("div", { class: "empty" }, t("t.noModels")));
  TR.models.forEach(m => {
    const picker = h("input", { type: "file", accept: "image/*", hidden: true, onchange: async e => {
      const file = e.target.files[0]; e.target.value = "";
      if (!file) return;
      const res2 = await jpost("/v1/vision/predict", { model: m.name, image: await fileToDataUrl(file, 1280) });
      TR.test[m.name] = res2.ok ? { ok: true, data: res2.data } : { ok: false, text: errText(res2) };
      renderTrain();
    } });
    const box = h("div", { class: "model" }, picker, h("div", { class: "model-head" }, h("strong", {}, m.name), h("span", { class: "spacer" }),
      h("button", { class: "btn small", type: "button", onclick: () => picker.click() }, t("t.test")),
      h("button", { class: "btn small", type: "button", onclick: () => { TR.result = m; renderTrain(); } }, t("t.result")),
      TR.confirm === "m:" + m.name
        ? h("button", { class: "btn small danger", type: "button", onclick: async () => { TR.confirm = ""; await jpost("/v1/vision/models/delete", { name: m.name }); if (TR.result && TR.result.name === m.name) TR.result = null; loadTrain(); } }, t("t.confirm"))
        : h("button", { class: "btn small danger", type: "button", onclick: () => { TR.confirm = "m:" + m.name; renderTrain(); } }, t("t.delModel"))));
    box.append(h("div", { class: "meta-line" }, m.classes.join(" / ")));
    box.append(h("div", { class: "meta-line" }, t("t.modelMeta", { classes: m.classes.length, feats: m.features.map(x => t("t.f." + x)).join("+"),
      algo: m.algo, acc: m.metrics && m.metrics.accuracy != null ? pct(m.metrics.accuracy) : "-", time: m.created || "" })));
    const test = TR.test[m.name];
    if (test && test.ok) {
      box.append(h("div", { class: "meta-line" }, t("t.testResult", { label: test.data.label, p: pct(test.data.prob) })));
      Object.keys(test.data.probs).forEach(k => box.append(barRow(k, test.data.probs[k], k === test.data.label)));
    } else if (test) box.append(h("div", { class: "prov-msg bad" }, test.text));
    mdCard.append(box);
  });
  mdCard.append(h("p", { class: "fine" }, t("t.useNote")));
  grid.append(h("div", { class: "col" }, trCard, mdCard));
  root.append(grid);
  renderTrain.progress();
}
renderTrain.progress = function () {
  const bar = $("#t-job-bar"), text = $("#t-job-text");
  if (!bar || !text) return;
  bar.hidden = !TR.job;
  if (!TR.job) { text.textContent = ""; return; }
  bar.firstChild.style.width = Math.round((TR.job.progress || 0) * 100) + "%";
  text.textContent = stageName(TR.job.stage) + "  " + Math.round((TR.job.progress || 0) * 100) + "%";
};

/* ---------- 目标检测：数据集、画框标注、训练、模型 ---------- */
const TRAIN_TAB_KEY = "laya-workbench-train-tab";
const DT = {
  tab: "cls", loaded: false, datasets: [], models: [], dataset: "", items: null, total: 0, offset: 0, limit: 60, classes: [], recipes: null,
  lab: { file: null, image: null, img: null, w: 0, h: 0, boxes: [], sel: -1, cls: "", dirty: false, msg: null },
  form: { name: "", arch: "ssdlite", epochs: 20, batch: 8, imgsz: 320, pretrained: "auto", holdout: 0.15, resume: false },
  job: null, jobKind: "", msg: null, result: null, test: {}, scene: "weed", count: 40, confirm: "", recipe: "", conf: 0.4
};
try { const saved = localStorage.getItem(TRAIN_TAB_KEY); if (saved === "det" || saved === "cls") DT.tab = saved; } catch (e) { /* 用默认子页 */ }
function setTrainTab(tab) {
  DT.tab = tab === "det" ? "det" : "cls";
  try { localStorage.setItem(TRAIN_TAB_KEY, DT.tab); } catch (e) { /* 记不住也没关系 */ }
  renderTrain();
}
function detInfo() { const v = vision(); return (v && v.health && v.health.detect) || null; }
function detReady() { const d = detInfo(); return !!(d && d.available); }
function fmtEta(sec) {
  if (sec == null) return "-";
  sec = Math.max(0, Math.round(sec));
  if (sec < 90) return sec + " s";
  if (sec < 5400) return Math.round(sec / 60) + " min";
  return (sec / 3600).toFixed(1) + " h";
}
function imgUrl(name, file, thumb) {
  return "/v1/vision/det/datasets/image?name=" + encodeURIComponent(name) + "&file=" + encodeURIComponent(file) + (thumb ? "&thumb=1" : "");
}

async function loadDetect() {
  if (!visionReady()) { DT.loaded = false; return; }
  const [a, b] = await Promise.all([jget("/v1/vision/det/datasets"), jget("/v1/vision/det/models")]);
  DT.datasets = a.ok ? a.data.datasets : [];
  DT.models = b.ok ? b.data.models : [];
  if (!DT.datasets.some(d => d.name === DT.dataset)) { DT.dataset = DT.datasets.length ? DT.datasets[0].name : ""; DT.items = null; DT.offset = 0; }
  const ds = DT.datasets.find(d => d.name === DT.dataset);
  DT.classes = ds ? ds.classes.slice() : [];
  if (DT.lab.cls && !DT.classes.includes(DT.lab.cls)) DT.classes.push(DT.lab.cls);
  if (!DT.form.name) DT.form.name = DT.dataset ? DT.dataset + "-det" : "";
  if (DT.dataset && DT.items === null) {
    const r = await jget("/v1/vision/det/datasets/items?name=" + encodeURIComponent(DT.dataset) + "&offset=" + DT.offset + "&limit=" + DT.limit);
    if (r.ok) { DT.items = r.data.items; DT.total = r.data.total; } else { DT.items = []; DT.total = 0; }
  }
  if (DT.recipes === null) {
    const r = await jget("/_wb/recipes?lang=" + LANG);
    DT.recipes = r.ok && Array.isArray(r.data) ? r.data : [];
    if (!DT.recipe && DT.recipes.length) DT.recipe = DT.recipes[0].id;
  }
  DT.loaded = true;
  renderTrain();
}
function selectDetDataset(name) {
  DT.dataset = name; DT.items = null; DT.offset = 0; DT.confirm = ""; DT.loaded = false;
  DT.form.name = name ? name + "-det" : "";
  resetLabeler(); DT.lab.cls = "";
  renderTrain();
}
async function detJob(kind, path, body, onDone) {
  if (DT.job) return;
  DT.msg = null; DT.jobKind = kind;
  const res = await jpost(path, body);
  if (!res.ok) { DT.msg = { cls: "bad", text: errText(res) }; return renderTrain(); }
  DT.job = res.data; renderTrain();
  const job = await pollJob(DT.job, cur => { DT.job = cur; renderDetect.progress(); });
  DT.job = null;
  if (job.state === "done") onDone(job.result);
  else if (job.state === "cancelled") DT.msg = { cls: "", text: t("det.cancelled") };
  else DT.msg = { cls: "bad", text: t("det.fail", { msg: job.error || "" }) };
  DT.loaded = false; DT.items = null; VM.loaded = false;
  renderTrain();
}
async function cancelDetJob() {
  if (!DT.job) return;
  await jpost("/v1/vision/jobs/cancel", { id: DT.job.id });
}
function startDetTrain() {
  const f = DT.form;
  const ds = DT.datasets.find(d => d.name === DT.dataset);
  if (!ds) { DT.msg = { cls: "bad", text: t("det.needDataset") }; return renderTrain(); }
  if (!ds.boxes) { DT.msg = { cls: "bad", text: t("det.needBoxes") }; return renderTrain(); }
  if (!f.name.trim()) { DT.msg = { cls: "bad", text: t("det.needName") }; return renderTrain(); }
  DT.result = null;
  detJob("train", "/v1/vision/det/train", { dataset: DT.dataset, name: f.name.trim(), arch: f.arch, epochs: Number(f.epochs) || 20, batch: Number(f.batch) || 8,
    imgsz: Number(f.imgsz) || 320, pretrained: f.pretrained, holdout: Number(f.holdout) || 0, resume: !!f.resume }, result => { DT.result = result; });
}

/* ---- 标注器 ---- */
function resetLabeler() { DT.lab = { file: null, image: null, img: null, w: 0, h: 0, boxes: [], sel: -1, cls: DT.lab.cls, dirty: false, msg: null }; }
function labelerLoadUrl(url, file, boxes) {
  return new Promise(resolve => {
    const img = new Image();
    img.onload = () => {
      DT.lab = { file: file || null, image: url, img: img, w: img.naturalWidth, h: img.naturalHeight, boxes: (boxes || []).map(b => ({ label: b.label, bbox: b.bbox.slice() })),
        sel: -1, cls: DT.lab.cls, dirty: false, msg: null };
      resolve(true);
    };
    img.onerror = () => { toast(t("det.imgFail", { msg: "decode" })); resolve(false); };
    img.src = url;
  });
}
async function labelerUseFile(file) {
  if (!file) return;
  try { await labelerLoadUrl(await fileToDataUrl(file, 1280), null, []); renderTrain(); } catch (e) { toast(t("det.imgFail", { msg: e.message })); }
}
async function labelerOpenItem(item) {
  try {
    const resp = await api(imgUrl(DT.dataset, item.file));
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    await labelerLoadUrl(await blobToDataUrl(await resp.blob()), item.file, item.boxes);
    renderTrain();
  } catch (e) { toast(t("det.imgFail", { msg: e.message })); }
}
function labelerStep(delta) {
  const items = DT.items || [];
  const idx = items.findIndex(i => i.file === DT.lab.file);
  const next = items[idx < 0 ? (delta > 0 ? 0 : items.length - 1) : idx + delta];
  if (next) labelerOpenItem(next);
}
async function labelerSave() {
  const lab = DT.lab;
  if (!lab.image || !DT.dataset) { toast(t("det.needDataset")); return; }
  let res;
  if (lab.file) res = await jpost("/v1/vision/det/datasets/label", { name: DT.dataset, file: lab.file, boxes: lab.boxes });
  else res = await jpost("/v1/vision/det/datasets/add", { name: DT.dataset, image: lab.image, boxes: lab.boxes, size: [lab.w, lab.h] });
  if (!res.ok) { lab.msg = { cls: "bad", text: errText(res) }; return renderTrain(); }
  lab.file = res.data.file; lab.boxes = res.data.boxes.map(b => ({ label: b.label, bbox: b.bbox.slice() })); lab.dirty = false; lab.sel = -1;
  lab.msg = { cls: "ok", text: t("det.saved") };
  DT.classes = res.data.classes.slice();
  DT.loaded = false; DT.items = null;
  renderTrain();
}
async function labelerPrelabel() {
  const lab = DT.lab;
  if (!lab.file) { toast(t("det.saveFirst")); return; }
  const item = (DT.recipes || []).find(r => r.id === DT.recipe);
  if (!item) return;
  const res = await jpost("/v1/vision/det/datasets/prelabel", { name: DT.dataset, file: lab.file, recipe: item.recipe });
  if (!res.ok) { lab.msg = { cls: "bad", text: errText(res) }; return renderTrain(); }
  lab.boxes = res.data.boxes.map(b => ({ label: b.label, bbox: b.bbox.slice() }));
  res.data.boxes.forEach(b => { if (b.label && !DT.classes.includes(b.label)) DT.classes.push(b.label); });
  lab.dirty = true; lab.sel = -1; lab.msg = { cls: "", text: t("det.prelabeled", { n: lab.boxes.length }) };
  renderTrain();
}
async function labelerDeleteImage() {
  if (!DT.lab.file) return;
  await jpost("/v1/vision/det/datasets/delete", { name: DT.dataset, file: DT.lab.file });
  resetLabeler(); DT.loaded = false; DT.items = null; renderTrain();
}
function drawLabeler(canvas, temp) {
  const lab = DT.lab;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (lab.img) ctx.drawImage(lab.img, 0, 0, canvas.width, canvas.height);
  const lw = Math.max(1, canvas.width / 480);
  const palette = ["#14b8a6", "#e11d48", "#f59e0b", "#3b82f6", "#a855f7", "#84cc16", "#f97316", "#06b6d4"];
  ctx.font = Math.max(11, canvas.width / 55) + "px sans-serif";
  lab.boxes.forEach((b, i) => {
    const ci = Math.max(0, DT.classes.indexOf(b.label));
    const color = palette[ci % palette.length];
    const [x, y, w, hh] = b.bbox;
    ctx.lineWidth = i === lab.sel ? lw * 2.5 : lw;
    ctx.strokeStyle = color;
    ctx.strokeRect(x + 0.5, y + 0.5, w, hh);
    if (i === lab.sel) { ctx.fillStyle = "rgba(255,255,255,0.18)"; ctx.fillRect(x, y, w, hh); }
    const text = b.label || "?";
    const tw = ctx.measureText(text).width + 6, th = Math.max(13, canvas.width / 48);
    const ty = y - th >= 0 ? y - th : y + hh;
    ctx.fillStyle = color; ctx.fillRect(x, ty, tw, th);
    ctx.fillStyle = "#fff"; ctx.fillText(text, x + 3, ty + th - 3);
  });
  if (temp) { ctx.setLineDash([lw * 3, lw * 3]); ctx.lineWidth = lw; ctx.strokeStyle = "#fff"; ctx.strokeRect(temp[0] + 0.5, temp[1] + 0.5, temp[2], temp[3]); ctx.setLineDash([]); }
}
function hitBox(x, y) {
  let best = -1, area = Infinity;
  DT.lab.boxes.forEach((b, i) => {
    const [bx, by, bw, bh] = b.bbox;
    if (x >= bx && y >= by && x <= bx + bw && y <= by + bh && bw * bh < area) { best = i; area = bw * bh; }
  });
  return best;
}
function labelerCanvas() {
  const lab = DT.lab;
  const canvas = h("canvas", { id: "d-canvas", width: lab.w, height: lab.h, style: "max-width:100%;height:auto;display:block;touch-action:none;cursor:crosshair;border-radius:12px;background:#16232b" });
  let drag = null;
  const pos = e => { const r = canvas.getBoundingClientRect(); return [Math.round((e.clientX - r.left) * canvas.width / r.width), Math.round((e.clientY - r.top) * canvas.height / r.height)]; };
  const clamp = (v, max) => Math.max(0, Math.min(max, v));
  canvas.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    e.preventDefault();
    const [x, y] = pos(e);
    const hit = hitBox(x, y);
    if (hit >= 0 && hit !== lab.sel) { lab.sel = hit; drawLabeler(canvas); renderLabelerBar(); return; }
    if (hit >= 0 && hit === lab.sel) { lab.sel = -1; drawLabeler(canvas); renderLabelerBar(); return; }
    if (!(lab.cls || DT.classes[0])) { toast(t("det.needClass")); return; }
    drag = [x, y];
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", e => {
    if (!drag) return;
    const [x, y] = pos(e);
    drawLabeler(canvas, [Math.min(drag[0], x), Math.min(drag[1], y), Math.abs(x - drag[0]), Math.abs(y - drag[1])]);
  });
  const finish = e => {
    if (!drag) return;
    const [x, y] = pos(e);
    const x0 = clamp(Math.min(drag[0], x), lab.w), y0 = clamp(Math.min(drag[1], y), lab.h);
    const x1 = clamp(Math.max(drag[0], x), lab.w), y1 = clamp(Math.max(drag[1], y), lab.h);
    drag = null;
    if (x1 - x0 >= 4 && y1 - y0 >= 4) {
      lab.boxes.push({ label: lab.cls || DT.classes[0], bbox: [x0, y0, x1 - x0, y1 - y0] });
      lab.sel = lab.boxes.length - 1; lab.dirty = true;
    }
    drawLabeler(canvas); renderLabelerBar();
  };
  canvas.addEventListener("pointerup", finish);
  canvas.addEventListener("pointercancel", () => { drag = null; drawLabeler(canvas); });
  drawLabeler(canvas);
  return canvas;
}
function deleteSelectedBox() {
  const lab = DT.lab;
  if (lab.sel < 0) return;
  lab.boxes.splice(lab.sel, 1); lab.sel = -1; lab.dirty = true;
  const canvas = $("#d-canvas"); if (canvas) drawLabeler(canvas);
  renderLabelerBar();
}
function renderLabelerBar() {
  const bar = $("#d-labbar");
  if (!bar) return;
  bar.textContent = "";
  const lab = DT.lab;
  const clsSel = h("select", { class: "inline-input", "aria-label": t("det.cls"), onchange: e => { lab.cls = e.target.value; } });
  DT.classes.forEach(c => clsSel.append(h("option", { value: c }, c)));
  if (!DT.classes.includes(lab.cls)) lab.cls = DT.classes[0] || "";
  clsSel.value = lab.cls;
  const newCls = h("input", { class: "inline-input", placeholder: t("det.newClass") });
  const addCls = () => {
    const name = newCls.value.trim().replace(/\s+/g, "_");
    if (!name) return toast(t("det.needName"));
    if (!DT.classes.includes(name)) DT.classes.push(name);
    lab.cls = name; newCls.value = ""; renderLabelerBar(); const c = $("#d-canvas"); if (c) drawLabeler(c);
  };
  newCls.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); addCls(); } });
  bar.append(h("div", { class: "rowline" }, h("span", { class: "hint" }, t("det.cls")), DT.classes.length ? clsSel : null, newCls,
    h("button", { class: "btn small", type: "button", onclick: addCls }, t("det.addClass")),
    h("span", { class: "spacer" }), h("span", { class: "hint" }, t("det.boxes", { n: lab.boxes.length }) + (lab.dirty ? "　·　" + t("det.unsaved") : ""))));
  if (lab.sel >= 0 && lab.boxes[lab.sel]) {
    const box = lab.boxes[lab.sel];
    const boxSel = h("select", { class: "inline-input", "aria-label": t("det.boxCls"), onchange: e => { box.label = e.target.value; lab.dirty = true; const c = $("#d-canvas"); if (c) drawLabeler(c); } });
    DT.classes.forEach(c => boxSel.append(h("option", { value: c }, c)));
    boxSel.value = box.label;
    bar.append(h("div", { class: "rowline" }, h("span", { class: "hint" }, t("det.boxCls")), boxSel, h("code", {}, "#" + (lab.sel + 1) + " [" + box.bbox.join(", ") + "]"),
      h("button", { class: "btn small danger", type: "button", onclick: deleteSelectedBox }, t("det.delBox"))));
  }
}

function renderDetect(root, health) {
  const info = detInfo();
  const envLine = h("div", { class: "vstatus" }, h("span", { class: "dot " + (detReady() ? "ok" : "bad") }),
    detReady() ? t("det.env.ready", { t: info.torch, tv: info.torchvision, dev: info.device || "auto" }) : t("det.env.missing", { why: (info && info.reason) || "?" }));
  root.append(h("section", { class: "card intro" }, envLine, h("p", { class: "fine", style: "margin-bottom:0" }, t("det.intro"))));
  if (!DT.loaded) { loadDetect(); return; }
  const grid = h("main", { class: "grid" });
  const left = h("div", { class: "col" });

  /* 数据集 */
  const dsCard = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("det.datasets"))));
  const select = h("select", { class: "inline-input grow", "aria-label": t("t.dataset"), onchange: e => selectDetDataset(e.target.value) });
  DT.datasets.forEach(d => select.append(h("option", { value: d.name }, d.name + "  (" + d.images + ")")));
  select.value = DT.dataset;
  const newName = h("input", { class: "inline-input grow", placeholder: t("det.newName") });
  const newClasses = h("input", { class: "inline-input grow", placeholder: t("det.newClasses") });
  dsCard.append(h("div", { class: "rowline" }, DT.datasets.length ? select : null, newName, newClasses,
    h("button", { class: "btn small", type: "button", onclick: async () => {
      const name = newName.value.trim();
      if (!name) return toast(t("det.needName"));
      const res = await jpost("/v1/vision/det/datasets/create", { name: name, classes: newClasses.value });
      if (!res.ok) return toast(errText(res));
      selectDetDataset(res.data.name);
    } }, t("det.create"))));
  const scene = h("select", { class: "inline-input", "aria-label": t("t.demoScene"), onchange: e => { DT.scene = e.target.value; } });
  Object.keys(health.scenes || {}).forEach(name => scene.append(h("option", { value: name }, name)));
  scene.value = DT.scene;
  const count = h("input", { class: "inline-input", type: "number", min: "4", max: "500", value: String(DT.count), "aria-label": t("det.demoCount"), style: "width:80px", oninput: e => { DT.count = Number(e.target.value) || 40; } });
  dsCard.append(h("div", { class: "rowline" }, h("span", { class: "hint" }, t("det.demoGen")), scene, h("span", { class: "hint" }, t("det.demoCount")), count,
    h("button", { class: "btn small", type: "button", disabled: !!DT.job, onclick: () => detJob("dataset", "/v1/vision/det/datasets/demo", { scene: DT.scene, count: DT.count },
      result => { DT.dataset = result.name; DT.form.name = result.name + "-det"; resetLabeler(); DT.msg = { cls: "ok", text: t("det.generated", { name: result.name, n: result.images, b: result.boxes }) + (LANG === "en" ? " " : "") + t("det.synthNote") }; }) },
      DT.job && DT.jobKind === "dataset" ? t("det.generating") : t("det.demoGen"))));
  const ds = DT.datasets.find(d => d.name === DT.dataset);
  if (!ds) dsCard.append(h("div", { class: "empty" }, t("det.noDataset")));
  else {
    dsCard.append(h("div", { class: "rowline" }, h("span", { class: "hint grow" }, t("det.meta", { n: ds.images, b: ds.boxes, c: ds.classes.length ? ds.classes.join(" / ") : t("det.noClasses") })),
      DT.confirm === "d" ? h("button", { class: "btn small danger", type: "button", onclick: async () => { DT.confirm = ""; await jpost("/v1/vision/det/datasets/delete", { name: ds.name }); selectDetDataset(""); } }, t("det.confirm"))
        : h("button", { class: "btn small danger", type: "button", onclick: () => { DT.confirm = "d"; renderTrain(); } }, t("det.delDataset"))));
    const items = DT.items || [];
    if (!items.length) dsCard.append(h("div", { class: "empty" }, t("det.noItems")));
    else {
      const thumbs = h("div", { class: "thumbs" });
      items.forEach(item => {
        const wrap = h("span", { style: "position:relative;display:inline-block;cursor:pointer", title: item.file + "  " + t("det.boxes", { n: item.boxes.length }), onclick: () => labelerOpenItem(item) },
          h("img", { loading: "lazy", alt: "", src: imgUrl(ds.name, item.file, true), style: item.file === DT.lab.file ? "outline:3px solid var(--teal)" : "" }),
          h("span", { style: "position:absolute;right:2px;bottom:2px;background:rgba(22,35,43,.8);color:#fff;font-size:10px;padding:0 4px;border-radius:4px;line-height:14px" }, String(item.boxes.length)));
        thumbs.append(wrap);
      });
      dsCard.append(thumbs);
      dsCard.append(h("div", { class: "rowline", style: "margin-top:8px" }, h("span", { class: "hint grow" }, t("det.itemsCount", { n: DT.total, a: DT.offset + 1, b: DT.offset + items.length })),
        h("button", { class: "btn small", type: "button", disabled: DT.offset <= 0, onclick: () => { DT.offset = Math.max(0, DT.offset - DT.limit); DT.items = null; DT.loaded = false; renderTrain(); } }, t("det.prevPage")),
        h("button", { class: "btn small", type: "button", disabled: DT.offset + DT.limit >= DT.total, onclick: () => { DT.offset += DT.limit; DT.items = null; DT.loaded = false; renderTrain(); } }, t("det.nextPage"))));
    }
  }
  if (DT.msg && DT.jobKind === "dataset") dsCard.append(h("div", { class: "prov-msg " + DT.msg.cls }, DT.msg.text));
  left.append(dsCard);

  /* 标注器 */
  const lab = DT.lab;
  const labCard = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("det.labeler"))));
  const fileInput = h("input", { type: "file", accept: "image/*", hidden: true, onchange: e => { const f = e.target.files[0]; e.target.value = ""; labelerUseFile(f); } });
  labCard.append(fileInput);
  if (lab.image) labCard.append(h("div", { class: "imgbox", style: "line-height:0" }, labelerCanvas()), h("p", { class: "fine", style: "margin:6px 0" }, t("det.dropSmall")));
  else labCard.append(h("div", { class: "drop", role: "button", tabindex: "0", onclick: () => fileInput.click(),
    onkeydown: e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } } }, t("det.drop"), h("small", {}, t("det.dropSmall"))));
  labCard.addEventListener("dragover", e => { e.preventDefault(); const d = $(".drop", labCard); if (d) d.classList.add("over"); });
  labCard.addEventListener("dragleave", () => { const d = $(".drop", labCard); if (d) d.classList.remove("over"); });
  labCard.addEventListener("drop", e => { e.preventDefault(); const f = imageFiles(e.dataTransfer.files)[0]; if (f) labelerUseFile(f); });
  labCard.append(h("div", { id: "d-labbar" }));
  const nav = h("div", { class: "rowline" },
    h("button", { class: "btn small", type: "button", onclick: () => fileInput.click() }, t("det.pick")),
    h("button", { class: "btn small", type: "button", disabled: !(DT.items && DT.items.length), onclick: () => labelerStep(-1) }, t("det.prev")),
    h("button", { class: "btn small", type: "button", disabled: !(DT.items && DT.items.length), onclick: () => labelerStep(1) }, t("det.next")),
    h("span", { class: "spacer" }),
    lab.image ? h("button", { class: "btn small", type: "button", onclick: () => { lab.boxes = []; lab.sel = -1; lab.dirty = true; renderTrain(); } }, t("det.clear")) : null,
    lab.file ? h("button", { class: "btn small danger", type: "button", onclick: labelerDeleteImage }, t("det.delImage")) : null,
    h("button", { class: "btn small primary", type: "button", disabled: !lab.image || !DT.dataset, onclick: labelerSave }, t("det.save")));
  labCard.append(nav);
  const recipeSel = h("select", { class: "inline-input grow", "aria-label": t("det.recipe"), onchange: e => { DT.recipe = e.target.value; } });
  (DT.recipes || []).forEach(r => recipeSel.append(h("option", { value: r.id }, r.title + (r.custom ? t("v.custom") : ""))));
  recipeSel.value = DT.recipe;
  labCard.append(h("div", { class: "rowline" }, h("span", { class: "hint" }, t("det.recipe")), recipeSel,
    h("button", { class: "btn small", type: "button", disabled: !lab.file || !DT.recipe, title: lab.file ? "" : t("det.saveFirst"), onclick: labelerPrelabel }, t("det.prelabel"))));
  labCard.append(h("p", { class: "fine" }, t("det.prelabelHint")));
  if (lab.msg) labCard.append(h("div", { class: "prov-msg " + (lab.msg.cls || "") }, lab.msg.text));
  left.append(labCard);
  grid.append(left);

  /* 训练 */
  const f = DT.form;
  const right = h("div", { class: "col" });
  const trCard = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("det.train"))));
  trCard.append(h("div", { class: "vfield" }, h("label", { for: "d-name" }, t("det.modelName")), h("input", { id: "d-name", type: "text", value: f.name, oninput: e => { f.name = e.target.value; } })));
  const arch = h("select", { id: "d-arch", onchange: e => { f.arch = e.target.value; } });
  ((info && info.archs) || ["ssdlite", "fasterrcnn_mobile"]).forEach(name => arch.append(h("option", { value: name }, I18N.zh["det.arch." + name] ? t("det.arch." + name) : name)));
  arch.value = f.arch;
  trCard.append(h("div", { class: "vfield" }, h("label", { for: "d-arch" }, t("det.arch")), arch));
  const num = (key, label, min, max, step) => h("div", { class: "vfield", style: "flex:1 1 90px" }, h("label", {}, label),
    h("input", { type: "number", min: String(min), max: String(max), step: String(step || 1), value: String(f[key]), style: "width:100%", oninput: e => { f[key] = e.target.value; } }));
  trCard.append(h("div", { style: "display:flex;gap:10px;flex-wrap:wrap" }, num("epochs", t("det.epochs"), 1, 500), num("batch", t("det.batch"), 1, 64), num("imgsz", t("det.imgsz"), 96, 1024, 32), num("holdout", t("det.holdout"), 0, 0.5, 0.05)));
  const pre = h("select", { id: "d-pre", onchange: e => { f.pretrained = e.target.value; } });
  ["auto", "yes", "no"].forEach(v => pre.append(h("option", { value: v }, t("det.pre." + v))));
  pre.value = f.pretrained;
  trCard.append(h("div", { class: "vfield" }, h("label", { for: "d-pre" }, t("det.pretrained")), pre));
  trCard.append(h("div", { class: "checks", style: "margin-bottom:12px" }, h("label", { class: "check" }, h("input", { type: "checkbox", checked: f.resume || null, onchange: e => { f.resume = e.target.checked; } }), t("det.resume"))));
  const training = DT.job && DT.jobKind === "train";
  trCard.append(h("div", { class: "rowline" }, h("button", { class: "btn primary", type: "button", disabled: !!DT.job || !detReady(), onclick: startDetTrain }, training ? t("det.training") : t("det.start")),
    training ? h("button", { class: "btn small danger", type: "button", onclick: cancelDetJob }, t("det.cancel")) : null,
    h("span", { class: "hint", id: "d-job-text" })));
  trCard.append(h("div", { class: "progress", id: "d-job-bar", hidden: !training }, h("i")));
  trCard.append(h("pre", { class: "code", id: "d-job-log", hidden: !training, style: "max-height:160px;overflow:auto;font-size:12px" }));
  if (DT.msg && DT.jobKind === "train") trCard.append(h("div", { class: "prov-msg " + DT.msg.cls }, DT.msg.text));
  const res = DT.result;
  if (res) {
    trCard.append(h("div", { class: "sub" }, t("det.result"), h("small", {}, res.name || "")));
    if (res.map50 != null) trCard.append(h("div", { class: "acc" }, pct(res.map50), h("small", {}, t("det.map"))));
    else trCard.append(h("div", { class: "fine" }, t("det.mapNone")));
    trCard.append(h("p", { class: "fine" }, t("det.resultNote", { n: res.epochs_done, tr: res.train_images, ho: res.holdout_images, s: res.seconds, pre: res.pretrained_used ? t("det.preUsed") : t("det.preNo") }) +
      (res.oom_retries ? " " + t("det.oomNote", { n: res.oom_retries, b: res.batch }) : "")));
    const per = res.per_class || {};
    if (Object.keys(per).length) {
      const tb = h("tbody");
      Object.keys(per).forEach(c => tb.append(h("tr", {}, h("td", {}, c), h("td", { class: "num" }, per[c] == null ? "-" : pct(per[c])))));
      trCard.append(h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("det.th.class")), h("th", { class: "num" }, t("det.th.ap")))), tb)));
    }
    trCard.append(h("p", { class: "fine" }, t("det.synthNote")));
  }
  right.append(trCard);

  /* 模型 */
  const mdCard = h("section", { class: "card" }, h("div", { class: "head" }, h("h2", {}, t("det.models")),
    h("label", { class: "check" }, t("det.conf"), h("input", { type: "number", min: "0.05", max: "0.95", step: "0.05", value: String(DT.conf), style: "width:70px;margin-left:6px", oninput: e => { DT.conf = Number(e.target.value) || 0.4; } }))));
  if (!DT.models.length) mdCard.append(h("div", { class: "empty" }, t("det.noModels")));
  DT.models.forEach(m => {
    const picker = h("input", { type: "file", accept: "image/*", hidden: true, onchange: async e => {
      const file = e.target.files[0]; e.target.value = "";
      if (!file) return;
      const res2 = await jpost("/v1/vision/det/predict", { model: m.name, image: await fileToDataUrl(file, 1280), conf: DT.conf });
      DT.test[m.name] = res2.ok ? { ok: true, data: res2.data, conf: DT.conf } : { ok: false, text: errText(res2) };
      renderTrain();
    } });
    const box = h("div", { class: "model" }, picker, h("div", { class: "model-head" }, h("strong", {}, m.name), h("span", { class: "spacer" }),
      h("button", { class: "btn small", type: "button", disabled: !detReady(), onclick: () => picker.click() }, t("det.test")),
      h("button", { class: "btn small", type: "button", onclick: () => { DT.result = Object.assign({ name: m.name, train_images: m.train_images, holdout_images: m.holdout_images, seconds: "-" }, m); renderTrain(); } }, t("det.result")),
      DT.confirm === "m:" + m.name
        ? h("button", { class: "btn small danger", type: "button", onclick: async () => { DT.confirm = ""; await jpost("/v1/vision/det/models/delete", { name: m.name }); if (DT.result && DT.result.name === m.name) DT.result = null; DT.loaded = false; renderTrain(); } }, t("det.confirm"))
        : h("button", { class: "btn small danger", type: "button", onclick: () => { DT.confirm = "m:" + m.name; renderTrain(); } }, t("det.delModel"))));
    box.append(h("div", { class: "meta-line" }, (m.classes || []).join(" / ")));
    box.append(h("div", { class: "meta-line" }, t("det.modelMeta", { arch: m.arch, n: (m.classes || []).length, m: m.map50 == null ? "-" : pct(m.map50), time: m.created || "" })));
    const test = DT.test[m.name];
    if (test && test.ok) {
      box.append(h("div", { class: "meta-line" }, t("det.testResult", { n: test.data.boxes.length, c: test.conf })));
      if (test.data.image) box.append(h("div", { class: "imgbox", style: "margin-top:6px" }, h("img", { src: test.data.image, alt: "" })));
    } else if (test) box.append(h("div", { class: "prov-msg bad" }, test.text));
    mdCard.append(box);
  });
  mdCard.append(h("p", { class: "fine" }, t("det.useNote")));
  right.append(mdCard);
  grid.append(right);
  root.append(grid);
  renderLabelerBar();
  renderDetect.progress();
}
renderDetect.progress = function () {
  const bar = $("#d-job-bar"), text = $("#d-job-text"), log = $("#d-job-log");
  if (!bar || !text) return;
  const job = DT.job && DT.jobKind === "train" ? DT.job : null;
  bar.hidden = !job; if (log) log.hidden = !job;
  if (!job) { text.textContent = ""; return; }
  bar.firstChild.style.width = Math.round((job.progress || 0) * 100) + "%";
  let line = stageName(job.stage) + "  " + Math.round((job.progress || 0) * 100) + "%";
  if (job.epoch != null) line += "　" + t("det.progress", { e: job.epoch, es: job.epochs || "?", s: job.step == null ? "-" : job.step, ss: job.steps == null ? "-" : job.steps, l: job.loss == null ? "-" : Number(job.loss).toFixed(3), eta: fmtEta(job.eta_seconds) });
  text.textContent = line;
  if (log) { log.textContent = (job.log_tail || []).slice(-12).join("\n"); log.scrollTop = log.scrollHeight; }
};
document.addEventListener("keydown", e => {
  if (S.view !== "train" || DT.tab !== "det" || !$("#d-canvas")) return;
  const tag = (e.target && e.target.tagName) || "";
  if ((e.key === "Delete" || e.key === "Backspace") && tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") { e.preventDefault(); deleteSelectedBox(); }
});

/* ---------- 对外 ---------- */
document.addEventListener("paste", e => {
  if (!e.clipboardData) return;
  const toLabeler = S.view === "train" && DT.tab === "det";
  if (S.view !== "vision" && !toLabeler) return;
  const tag = (e.target && e.target.tagName) || "";
  const file = imageFiles(e.clipboardData.files)[0];
  if (file && tag !== "TEXTAREA" && tag !== "INPUT") { e.preventDefault(); if (toLabeler) labelerUseFile(file); else useFile(file); }
});
let lastVisionState = "";
window.WBV = {
  run: runInspect,
  onModel: function () { syncDecisionSelect(); },
  onView: function () {
    if (S.view !== "vision") stopCamera();
    if (S.view === "vision") { VM.loaded = false; if (!V.loaded) loadRecipes(); else renderVision(); if (visionReady() && !TR.loaded) jget("/v1/vision/datasets").then(r => { if (r.ok) TR.datasets = r.data.datasets; }); }
    if (S.view === "train") { TR.loaded = false; DT.loaded = false; DT.items = null; renderTrain(); }
  },
  onStatus: function () {
    const v = vision();
    const state = JSON.stringify([S.status === undefined, !!S.status, v && v.mode, v && v.health && v.health.backbone && v.health.backbone.available,
      v && v.health && v.health.detect && v.health.detect.available]);
    if (state === lastVisionState) return;                 // 只在状态变化时重画，避免打断正在填写的内容
    lastVisionState = state;
    if (S.view === "vision") renderVision();
    if (S.view === "train") renderTrain();
  },
  onLang: function () {
    if (V.loaded || S.view === "vision") loadRecipes(true);
    DT.recipes = null;
    if (S.view === "train") { DT.loaded = false; renderTrain(); }
  }
};
})();
