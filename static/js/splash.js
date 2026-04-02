// Glass Splash: adapted from silicon-friendly °/° intro
(function() {
    var splash = document.getElementById('splash-screen');
    if (!splash) return;

    // Show splash once every 7 days
    var SPLASH_INTERVAL = 7 * 24 * 60 * 60 * 1000;
    var lastShown = localStorage.getItem('glass-splash-shown');
    if (lastShown && (Date.now() - parseInt(lastShown, 10)) < SPLASH_INTERVAL) {
        splash.style.display = 'none';
        return;
    }

    var splashDone = false;
    function dismissSplash() {
        if (splashDone) return;
        splashDone = true;
        cancelAnimationFrame(rafId);
        if (engine) { window.Matter && window.Matter.Engine.clear(engine); engine = null; }
        splash.style.transition = "opacity 0.6s ease";
        splash.style.opacity = "0";
        localStorage.setItem('glass-splash-shown', Date.now().toString());
        setTimeout(function() { splash.style.display = 'none'; }, 600);
    }

    setTimeout(dismissSplash, 15000);

    var CHAR_SET = "@#%&8B$WMQO0Xkdpbqo*+~=:-.` ";
    var COLS = 100;

    var canvas = document.getElementById('splash-canvas');
    var W = window.innerWidth;
    var H = window.innerHeight;
    var dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";
    var ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    var asciiOpen = [];
    var asciiWink = [];
    var fontPx = 0;
    var charW = 0;
    var charH = 0;
    var rafId = 0;
    var engine = null;
    var bodies = [];
    var nameText = "";
    var nameOpacity = 0;
    var fixedCanvasW = 0;
    var fixedCanvasH = 0;

    function initCanvasSize() {
        var oc = document.createElement("canvas").getContext("2d");
        var fs = 400;
        oc.font = fs + "px ApfelGrotezk";
        var w1 = oc.measureText("\u00B0/\u00B0").width;
        var w2 = oc.measureText("\u00B0/-").width;
        fixedCanvasW = Math.max(w1, w2) + 60;
        fixedCanvasH = fs + 60;
    }

    function buildAscii(text) {
        var off = document.createElement("canvas");
        var oc = off.getContext("2d");
        var fs = 400;
        off.width = fixedCanvasW;
        off.height = fixedCanvasH;
        oc.fillStyle = "#000";
        oc.fillRect(0, 0, off.width, off.height);
        oc.fillStyle = "#fff";
        oc.font = fs + "px ApfelGrotezk";
        oc.textBaseline = "top";
        oc.fillText(text, 30, 15);

        var cols = COLS;
        fontPx = Math.max(7, Math.floor(W * 0.7 / cols));
        ctx.font = fontPx + "px monospace";
        charW = ctx.measureText("@").width;
        charH = fontPx * 1.2;

        var displayRatio = charH / charW;
        var cellW = off.width / cols;
        var cellH = cellW * displayRatio;
        var rows = Math.floor(off.height / cellH);
        var img = oc.getImageData(0, 0, off.width, off.height);

        var gridW = cols * charW;
        var gridH = rows * charH;
        var ox = (W - gridW) / 2;
        var oy = (H - gridH) / 2;

        var chars = [];
        for (var r = 0; r < rows; r++) {
            for (var c = 0; c < cols; c++) {
                var sx = Math.floor(c * cellW);
                var sy = Math.floor(r * cellH);
                var ex = Math.min(Math.floor((c + 1) * cellW), off.width);
                var ey = Math.min(Math.floor((r + 1) * cellH), off.height);
                var sum = 0, cnt = 0;
                for (var y = sy; y < ey; y++) {
                    for (var x = sx; x < ex; x++) {
                        sum += img.data[(y * off.width + x) * 4];
                        cnt++;
                    }
                }
                var bright = cnt > 0 ? sum / cnt / 255 : 0;
                var ci = Math.floor((1 - bright) * (CHAR_SET.length - 1));
                var ch = CHAR_SET[ci] || " ";
                if (ch.trim() === "") continue;
                chars.push({
                    char: ch,
                    x: ox + c * charW + charW / 2,
                    y: oy + r * charH + charH / 2,
                    col: c, row: r
                });
            }
        }
        return chars;
    }

    function draw(chars) {
        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = "#1a1a1a";
        ctx.fillRect(0, 0, W, H);
        ctx.font = fontPx + "px monospace";
        ctx.fillStyle = "#ede8e0";
        ctx.textBaseline = "middle";
        ctx.textAlign = "center";
        for (var i = 0; i < chars.length; i++) {
            var c = chars[i];
            ctx.fillText(c.char, c.x, c.y);
        }
    }

    function blast() {
        var Matter = window.Matter;
        engine = Matter.Engine.create({ gravity: { x: 0, y: 2 } });
        var t = 60;
        Matter.Composite.add(engine.world, [
            Matter.Bodies.rectangle(W / 2, H + t / 2, W + 200, t, { isStatic: true }),
            Matter.Bodies.rectangle(-t / 2, H / 2, t, H * 3, { isStatic: true }),
            Matter.Bodies.rectangle(W + t / 2, H / 2, t, H * 3, { isStatic: true })
        ]);

        bodies = [];
        for (var i = 0; i < asciiOpen.length; i++) {
            var c = asciiOpen[i];
            var a = Math.random() * Math.PI * 2;
            var f = 0.01 + Math.random() * 0.03;
            var body = Matter.Bodies.rectangle(c.x, c.y, charW, charH, {
                restitution: 0.35, friction: 0.5, frictionAir: 0.003
            });
            Matter.Body.applyForce(body, { x: c.x, y: c.y }, {
                x: Math.cos(a) * f, y: Math.sin(a) * f - 0.02
            });
            Matter.Body.setAngularVelocity(body, (Math.random() - 0.5) * 0.3);
            bodies.push({ body: body, char: c.char });
            Matter.Composite.add(engine.world, body);
        }

        function render() {
            if (!engine) return;
            Matter.Engine.update(engine, 1000 / 60);
            ctx.clearRect(0, 0, W, H);
            ctx.fillStyle = "#1a1a1a";
            ctx.fillRect(0, 0, W, H);
            ctx.font = fontPx + "px monospace";
            ctx.fillStyle = "#ede8e0";
            ctx.textBaseline = "middle";
            ctx.textAlign = "center";
            for (var i = 0; i < bodies.length; i++) {
                var b = bodies[i];
                var pos = b.body.position;
                ctx.save();
                ctx.translate(pos.x, pos.y);
                ctx.rotate(b.body.angle);
                ctx.fillText(b.char, 0, 0);
                ctx.restore();
            }
            if (nameText) {
                ctx.save();
                ctx.globalAlpha = nameOpacity;
                ctx.font = "14px monospace";
                ctx.fillStyle = "#ede8e0";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(nameText, W / 2, H / 2);
                ctx.restore();
            }
            rafId = requestAnimationFrame(render);
        }
        render();
    }

    function sleep(ms) {
        return new Promise(function(r) { setTimeout(r, ms); });
    }

    async function run() {
        initCanvasSize();
        asciiOpen = buildAscii("\u00B0/\u00B0");
        asciiWink = buildAscii("\u00B0/-");

        draw(asciiOpen);
        await sleep(1200);
        draw(asciiWink);
        await sleep(400);
        draw(asciiOpen);
        await sleep(500);

        blast();
        await sleep(2500);
        nameText = "GLASS";
        for (var i = 0; i <= 20; i++) { nameOpacity = i / 20; await sleep(40); }
        await sleep(800);

        var stages = [
            "GLASS",
            "GLAS~",
            "GLA~~",
            "GL~~~",
            "G~~~~",
            "~~~~~",
            "+++++",
            "*****",
            ":::::",
            "-----",
            "_____",
            ".....",
            "     "
        ];
        for (var s = 0; s < stages.length; s++) { nameText = stages[s]; await sleep(50); }

        nameOpacity = 0;
        await sleep(400);
        dismissSplash();
    }

    var font = new FontFace("ApfelGrotezk", "url(/static/fonts/ApfelGrotezk-Regular.woff2)");
    font.load().then(function(loaded) {
        document.fonts.add(loaded);
        run();
    });
})();
