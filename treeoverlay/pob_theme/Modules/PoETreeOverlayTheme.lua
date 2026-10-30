-- macOS-style look for Path of Building, installed by PoE Tree Overlay.
-- Dark by default; %APPDATA%/PoE Tree Overlay/pob_theme.cfg with light=1
-- switches to the light palette (and dark text on it).
--
-- PoB draws every box the same way: the border as a filled rectangle, then the
-- fill one pixel inside it. This module wraps PoB's drawing functions, spots
-- that pair and draws it as a rounded box instead, and maps PoB's opaque greys
-- to the macOS dark palette. Coloured frames (the Calcs sections) are toned
-- down towards that palette, and the textured background behind the tabs is a
-- plain window colour. Images, text colours and anything translucent are left
-- as they are. The UI font (Inter) comes with it as SimpleGraphic fonts.
--
-- To undo by hand: delete this file and the PoE Tree Overlay line in
-- Modules/Main.lua (or turn the look off in PoE Tree Overlay's settings).

local realSetDrawColor, realDrawImage = SetDrawColor, DrawImage
local realDrawImageQuad, realDrawImageRotated = DrawImageQuad, DrawImageRotated
local realDrawString, realSetDrawLayer, realSetViewport = DrawString, SetDrawLayer, SetViewport

local disc = NewImageHandle()
disc:Load("Assets/PoETreeOverlay_round.png", "CLAMP")

local LIGHT = false
do
	local f = io.open((os.getenv("APPDATA") or ".") .. "/PoE Tree Overlay/pob_theme.cfg", "r")
	if f then
		LIGHT = (f:read("*a") or ""):find("light=1", 1, true) ~= nil
		f:close()
	end
end

-- PoB grey -> macOS dark grey. PoB's light greys (0.66-0.85) are frames and
-- dividers between panels: those become quiet separators.
local GREYS = {
	{ 0.00, 0.078, 0.078, 0.086 },   -- #141416 window
	{ 0.10, 0.102, 0.102, 0.110 },   -- #1a1a1c panels
	{ 0.15, 0.125, 0.125, 0.133 },   -- #202022
	{ 0.33, 0.165, 0.165, 0.173 },   -- #2a2a2c
	{ 0.50, 0.220, 0.220, 0.227 },   -- #38383a borders
	{ 0.66, 0.220, 0.220, 0.227 },
	{ 0.85, 0.173, 0.173, 0.180 },   -- #2c2c2e separators
	{ 0.99, 0.173, 0.173, 0.180 },
	{ 1.00, 1.000, 1.000, 1.000 },
}
if LIGHT then
	GREYS = {
		{ 0.00, 0.925, 0.925, 0.929 },   -- #ececed window
		{ 0.10, 0.961, 0.961, 0.965 },   -- #f5f5f6 panels
		{ 0.15, 0.973, 0.973, 0.976 },
		{ 0.33, 0.902, 0.902, 0.906 },   -- #e6e6e7
		{ 0.50, 0.780, 0.780, 0.788 },   -- #c7c7c9 borders
		{ 0.66, 0.780, 0.780, 0.788 },
		{ 0.85, 0.851, 0.851, 0.859 },   -- #d9d9db separators
		{ 0.99, 0.851, 0.851, 0.859 },
		{ 1.00, 0.640, 0.640, 0.650 },   -- white fills (scrollbar thumbs): mid grey
	}
end
local ACCENT = LIGHT and { 0.0, 0.478, 1.0 } or { 0.039, 0.518, 1.0 }    -- #0a84ff / #007aff
local CONTROL = LIGHT and { 1.0, 1.0, 1.0 } or { 0.173, 0.173, 0.180 }   -- buttons, fields, drop-downs
local CONTROL_HOVER = LIGHT and { 0.918, 0.918, 0.925 } or { 0.227, 0.227, 0.235 }
local COLOURED = 0.6                       -- how much of a coloured frame's colour is kept
local TINT_FILL = LIGHT and 0.22 or 0.6    -- same for filled rows: pastel on the light palette

local function grey(v)
	local lo = GREYS[1]
	for i = 2, #GREYS do
		local hi = GREYS[i]
		if v <= hi[1] then
			local t = (v - lo[1]) / (hi[1] - lo[1])
			return lo[2] + (hi[2] - lo[2]) * t, lo[3] + (hi[3] - lo[3]) * t, lo[4] + (hi[4] - lo[4]) * t
		end
		lo = hi
	end
	return v, v, v
end

-- PoB's colour strings: "^xRRGGBB", or "^0".."^9" (only black and white are greys)
local function parse(str)
	local hex = str:match("^%^x(%x%x%x%x%x%x)")
	if hex then
		return tonumber(hex:sub(1, 2), 16) / 255, tonumber(hex:sub(3, 4), 16) / 255, tonumber(hex:sub(5, 6), 16) / 255
	end
	local code = str:match("^%^(%d)")
	if code == "0" then
		return 0, 0, 0
	elseif code == "7" then
		return 1, 1, 1
	end
end

-- the colour as PoB set it (restored after drawing a box); only opaque greys are
-- mapped, and colours set by string (frames, row tints) toned down in boxes
local lr, lg, lb, la = 1, 1, 1, nil
local cr = 1
local isGrey = false
local tint             -- {r, g, b} of an opaque colour set by string, if not a grey
local pending          -- a border waiting for its fill

function SetDrawColor(r, g, b, a)
	-- light mode: PoB's translucent near-black veils (tooltips, dimmers) go light
	if LIGHT and type(r) == "number" and a ~= nil and a < 1 and a >= 0.4 and r == g and g == b and r <= 0.2 then
		r, g, b = 0.97, 0.97, 0.975
	end
	lr, lg, lb, la = r, g, b, a
	tint = nil
	local pr, pg, pb, opaque = r, g, b, a == nil or a >= 1
	if type(r) == "string" then
		pr, pg, pb = parse(r)
		opaque = g == nil
	end
	isGrey = type(pr) == "number" and pr == pg and pg == pb and opaque
	if isGrey then
		cr = pr
	elseif type(r) == "string" and pr and opaque then
		tint = { pr, pg, pb }
	end
	if la ~= nil then
		return realSetDrawColor(r, g, b, a)
	elseif lg ~= nil then
		return realSetDrawColor(r, g, b)
	end
	return realSetDrawColor(r)
end

local function restore()
	if la ~= nil then
		realSetDrawColor(lr, lg, lb, la)
	elseif lg ~= nil then
		realSetDrawColor(lr, lg, lb)
	else
		realSetDrawColor(lr)
	end
end

local function roundRect(x, y, w, h, r)
	if r < 2 then
		realDrawImage(nil, x, y, w, h)
		return
	end
	realDrawImage(disc, x, y, r, r, 0, 0, 0.5, 0.5)
	realDrawImage(disc, x + w - r, y, r, r, 0.5, 0, 1, 0.5)
	realDrawImage(disc, x, y + h - r, r, r, 0, 0.5, 0.5, 1)
	realDrawImage(disc, x + w - r, y + h - r, r, r, 0.5, 0.5, 1, 1)
	realDrawImage(nil, x + r, y, w - 2 * r, h)
	realDrawImage(nil, x, y + r, r, h - 2 * r)
	realDrawImage(nil, x + w - r, y + r, r, h - 2 * r)
end

local function radius(w, h)
	local r = (h <= 40 and w <= 600) and 6 or 8
	return math.floor(math.min(r, w / 2, h / 2))
end

-- a coloured frame or row tint, part way towards the panel grey
local function toned(c, k)
	k = k or COLOURED
	local gr, gg, gb = grey(0.1)
	return gr + (c[1] - gr) * k, gg + (c[2] - gg) * k, gb + (c[3] - gb) * k
end

local function setBorder(b)
	if b.tint then
		realSetDrawColor(toned(b.tint))
	elseif b.v >= 1 then                 -- white border: hovered, selected or focused
		realSetDrawColor(ACCENT[1], ACCENT[2], ACCENT[3])
	else
		realSetDrawColor(grey(b.v))
	end
end

local function drawBox(b, fill, inset)
	local r = radius(b.w, b.h)
	setBorder(b)
	roundRect(b.x, b.y, b.w, b.h, r)
	if fill == 0 and b.h <= 40 then
		realSetDrawColor(CONTROL[1], CONTROL[2], CONTROL[3])
	elseif b.v >= 1 and fill > 0.3 and fill < 0.4 and b.h <= 40 then
		realSetDrawColor(CONTROL_HOVER[1], CONTROL_HOVER[2], CONTROL_HOVER[3])
	else
		realSetDrawColor(grey(fill))
	end
	roundRect(b.x + inset, b.y + inset, b.w - 2 * inset, b.h - 2 * inset, math.max(0, r - inset))
	restore()
end

local function flush()
	local b = pending
	if b then
		pending = nil
		if b.tint then
			realSetDrawColor(toned(b.tint, TINT_FILL))
		else
			setBorder(b)
		end
		realDrawImage(nil, b.x, b.y, b.w, b.h)
		restore()
	end
end

local function inside(b, x, y, w, h, inset)
	return x == b.x + inset and y == b.y + inset and w == b.w - 2 * inset and h == b.h - 2 * inset
end

function DrawImage(handle, x, y, w, h, ...)
	if handle == nil and (isGrey or tint) and select("#", ...) == 0 and type(x) == "number" then
		local b = pending
		-- a border (grey, or a coloured frame 1-2 px wide) and its grey fill
		if b and isGrey and (inside(b, x, y, w, h, 1) or (b.tint and inside(b, x, y, w, h, 2))) then
			pending = nil
			drawBox(b, cr, x - b.x)
			return
		end
		flush()
		if w >= 8 and h >= 8 then
			pending = { x = x, y = y, w = w, h = h, v = cr, tint = tint }
			return
		end
		if tint then
			realSetDrawColor(toned(tint, TINT_FILL))
		else
			realSetDrawColor(grey(cr))
		end
		realDrawImage(nil, x, y, w, h)
		restore()
		return
	end
	flush()
	return realDrawImage(handle, x, y, w, h, ...)
end

function DrawImageQuad(...)
	flush()
	return realDrawImageQuad(...)
end

if realDrawImageRotated then
	function DrawImageRotated(...)
		flush()
		return realDrawImageRotated(...)
	end
end

-- Light mode text: PoB writes white on dark, so light greys flip to dark text
-- and bright colours dim until they read on the light panels. The passive tree
-- is drawn with PoB's own functions and keeps its own colours.
local function textColour(r, g, b)
	if r == g and g == b then
		local v = math.min(r, 1.08 - r)
		return v, v, v
	end
	local lum = 0.299 * r + 0.587 * g + 0.114 * b
	if lum > 0.62 then
		return r * 0.62 / lum, g * 0.62 / lum, b * 0.62 / lum
	end
	return r, g, b
end

local CODES = { ["0"] = { 0, 0, 0 }, ["1"] = { 1, 0, 0 }, ["2"] = { 0, 1, 0 }, ["3"] = { 0, 0, 1 },
	["4"] = { 1, 1, 0 }, ["5"] = { 1, 0, 1 }, ["6"] = { 0, 1, 1 }, ["7"] = { 1, 1, 1 },
	["8"] = { 0.7, 0.7, 0.7 }, ["9"] = { 0.4, 0.4, 0.4 } }

local function mapEscape(r, g, b)
	r, g, b = textColour(r, g, b)
	return string.format("^x%02X%02X%02X",
		math.floor(r * 255 + 0.5), math.floor(g * 255 + 0.5), math.floor(b * 255 + 0.5))
end

local function mapCodes(text)
	text = text:gsub("%^x(%x%x%x%x%x%x)", function(hex)
		return mapEscape(tonumber(hex:sub(1, 2), 16) / 255,
			tonumber(hex:sub(3, 4), 16) / 255, tonumber(hex:sub(5, 6), 16) / 255)
	end)
	return (text:gsub("%^(%d)", function(d)
		local c = CODES[d]
		return c and mapEscape(c[1], c[2], c[3]) or ("^" .. d)
	end))
end

function DrawString(x, y, align, h, font, text)
	flush()
	if LIGHT and type(text) == "string" then
		local pr, pg, pb = lr, lg, lb
		if type(lr) == "string" then
			pr, pg, pb = parse(lr)
		end
		if type(pr) == "number" and type(pb) == "number" then
			local tr, tg, tb = textColour(pr, pg, pb)
			if type(la) == "number" then
				realSetDrawColor(tr, tg, tb, la)
			else
				realSetDrawColor(tr, tg, tb)
			end
		end
		realDrawString(x, y, align, h, font, mapCodes(text))
		restore()
		return
	end
	return realDrawString(x, y, align, h, font, text)
end

function SetDrawLayer(...)
	flush()
	return realSetDrawLayer(...)
end

function SetViewport(...)
	flush()
	return realSetViewport(...)
end

-- The passive tree is thousands of images a frame and has no boxes to round:
-- it is drawn with PoB's own functions, which saves the wrappers' cost. Its
-- tooltips get the look again.
local themed = { SetDrawColor = SetDrawColor, DrawImage = DrawImage, DrawImageQuad = DrawImageQuad,
	DrawImageRotated = DrawImageRotated, DrawString = DrawString, SetDrawLayer = SetDrawLayer, SetViewport = SetViewport }
local plain = { SetDrawColor = realSetDrawColor, DrawImage = realDrawImage, DrawImageQuad = realDrawImageQuad,
	DrawImageRotated = realDrawImageRotated, DrawString = realDrawString, SetDrawLayer = realSetDrawLayer,
	SetViewport = realSetViewport }

local function use(set)
	for name, func in pairs(set) do
		_G[name] = func
	end
end

local function drawWith(set, other, func, ...)
	flush()
	isGrey = false
	use(set)
	local result = { pcall(func, ...) }
	flush()
	use(other)
	if not result[1] then
		error(result[2], 0)
	end
	return unpack(result, 2)
end

local function wrapClasses()
	local classes = common and common.classes
	local view, tip = classes and classes.PassiveTreeView, classes and classes.Tooltip
	if not view or not tip or not main or not main.DrawBackground then
		return false
	end
	-- behind the tabs: the window colour instead of the tree's dark blue texture
	main.DrawBackground = function(_, viewPort)
		flush()
		realSetDrawLayer(nil, -100)
		realSetDrawColor(grey(0))
		realDrawImage(nil, viewPort.x, viewPort.y, viewPort.width, viewPort.height)
		realSetDrawLayer(nil, 0)
		restore()
	end
	local viewDraw, tipDraw = view.Draw, tip.Draw
	view.Draw = function(...)
		return drawWith(plain, themed, viewDraw, ...)
	end
	tip.Draw = function(...)
		if DrawImage == realDrawImage then
			return drawWith(themed, plain, tipDraw, ...)
		end
		return tipDraw(...)
	end
	return true
end

-- a border still waiting at the end of the frame
if launch and launch.OnFrame then
	local onFrame = launch.OnFrame
	local wrapped = false
	launch.OnFrame = function(...)
		wrapped = wrapped or wrapClasses()
		onFrame(...)
		flush()
	end
end
