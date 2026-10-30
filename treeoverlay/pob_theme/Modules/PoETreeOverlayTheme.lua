-- macOS-style look for Path of Building, installed by PoE Tree Overlay.
--
-- PoB draws every box the same way: the border as a filled rectangle, then the
-- fill one pixel inside it. This module wraps PoB's drawing functions, spots
-- that pair and draws it as a rounded box instead, and maps PoB's opaque greys
-- to the macOS dark palette. Images, text colours and anything translucent are
-- left as they are. The UI font (Inter) comes with it as SimpleGraphic fonts.
--
-- To undo by hand: delete this file and the PoE Tree Overlay line in
-- Modules/Main.lua (or turn the look off in PoE Tree Overlay's settings).

local realSetDrawColor, realDrawImage = SetDrawColor, DrawImage
local realDrawImageQuad, realDrawImageRotated = DrawImageQuad, DrawImageRotated
local realDrawString, realSetDrawLayer, realSetViewport = DrawString, SetDrawLayer, SetViewport

local disc = NewImageHandle()
disc:Load("Assets/PoETreeOverlay_round.png", "CLAMP")

-- PoB grey -> macOS dark grey. PoB's light greys (0.66-0.85) are frames and
-- dividers between panels: those become quiet separators.
local GREYS = {
	{ 0.00, 0.110, 0.110, 0.118 },   -- #1c1c1e window
	{ 0.10, 0.141, 0.141, 0.149 },
	{ 0.15, 0.173, 0.173, 0.180 },   -- #2c2c2e
	{ 0.33, 0.227, 0.227, 0.235 },   -- #3a3a3c
	{ 0.50, 0.282, 0.282, 0.290 },   -- #48484a borders
	{ 0.66, 0.282, 0.282, 0.290 },
	{ 0.85, 0.220, 0.220, 0.227 },   -- #38383a separators
	{ 0.99, 0.220, 0.220, 0.227 },
	{ 1.00, 1.000, 1.000, 1.000 },
}
local ACCENT = { 0.039, 0.518, 1.0 }       -- #0a84ff
local CONTROL = { 0.227, 0.227, 0.235 }    -- #3a3a3c: buttons, fields, drop-downs
local CONTROL_HOVER = { 0.282, 0.282, 0.290 }

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

-- the colour as PoB set it (restored after drawing a box); only opaque greys are mapped
local lr, lg, lb, la = 1, 1, 1, nil
local cr = 1
local isGrey = false
local pending          -- a border waiting for its fill

function SetDrawColor(r, g, b, a)
	lr, lg, lb, la = r, g, b, a
	isGrey = type(r) == "number" and r == g and g == b and (a == nil or a >= 1)
	if isGrey then
		cr = r
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

local function drawBox(b, fill)
	local r = radius(b.w, b.h)
	if b.v >= 1 then                     -- white border: hovered, selected or focused
		realSetDrawColor(ACCENT[1], ACCENT[2], ACCENT[3])
	else
		realSetDrawColor(grey(b.v))
	end
	roundRect(b.x, b.y, b.w, b.h, r)
	if fill == 0 and b.h <= 40 then
		realSetDrawColor(CONTROL[1], CONTROL[2], CONTROL[3])
	elseif b.v >= 1 and fill > 0.3 and fill < 0.4 and b.h <= 40 then
		realSetDrawColor(CONTROL_HOVER[1], CONTROL_HOVER[2], CONTROL_HOVER[3])
	else
		realSetDrawColor(grey(fill))
	end
	roundRect(b.x + 1, b.y + 1, b.w - 2, b.h - 2, math.max(0, r - 1))
	restore()
end

local function flush()
	local b = pending
	if b then
		pending = nil
		realSetDrawColor(grey(b.v))
		realDrawImage(nil, b.x, b.y, b.w, b.h)
		restore()
	end
end

function DrawImage(handle, x, y, w, h, ...)
	if handle == nil and isGrey and select("#", ...) == 0 and type(x) == "number" then
		local b = pending
		if b and x == b.x + 1 and y == b.y + 1 and w == b.w - 2 and h == b.h - 2 then
			pending = nil
			drawBox(b, cr)
			return
		end
		flush()
		if w >= 8 and h >= 8 then
			pending = { x = x, y = y, w = w, h = h, v = cr }
			return
		end
		realSetDrawColor(grey(cr))
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

function DrawString(...)
	flush()
	return realDrawString(...)
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
	if not view or not tip then
		return false
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
