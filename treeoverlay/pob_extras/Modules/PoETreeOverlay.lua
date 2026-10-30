-- PoE Tree Overlay's additions to Path of Building, installed by PoE Tree Overlay.
--
-- * speed: draws fewer frames while nothing happens (PoB otherwise redraws
--   the whole tree over 100 times a second, even in the background)
-- * link:  tells the overlay which build and tree are open, unsaved edits
--   included (pob_live.xml / pob_live.txt in the overlay's folder)
-- * marks: shows on PoB's tree what the overlay read from the game: passives
--   allocated in game (green ring, red if the tree doesn't have them) and the
--   next points in order (pob_marks.txt in the overlay's folder)
-- * keys:  Ctrl+Up / Ctrl+Down switch the build's tree on any tab
--
-- PoE Tree Overlay's settings say which of these are on (pob_extras.cfg).
-- To undo by hand: delete this file and the PoE Tree Overlay line in
-- Modules/Main.lua (or switch the options off in PoE Tree Overlay).

local DIR = (os.getenv("APPDATA") or ".") .. "/PoE Tree Overlay/"

local config = { }
do
	local f = io.open(DIR .. "pob_extras.cfg", "r")
	if f then
		for line in f:lines() do
			local key, value = line:match("^%s*([%w_]+)%s*=%s*(%S+)")
			if key then
				config[key] = value
			end
		end
		f:close()
	end
end
local function on(key)
	return config[key] == "1"
end

local debugLog = config.debug == "1" and io.open(DIR .. "pob_extras.log", "w")
local function debug(fmt, ...)
	if debugLog then
		debugLog:write(string.format(fmt, ...) .. "\n")
		debugLog:flush()
	end
end

local function buildMode()
	local b = main and main.mode == "BUILD" and main.modes and main.modes.BUILD
	if b and b.treeTab and b.spec then
		return b
	end
end

local frameHooks = { }
local onFrame = launch.OnFrame
local frames, drawTime, lastDebug = 0, 0, GetTime()
launch.OnFrame = function(...)
	local start = GetTime()
	onFrame(...)
	if debugLog then
		frames, drawTime = frames + 1, drawTime + GetTime() - start
		if start - lastDebug >= 2000 then
			debug("fps %.1f, %.1f ms per frame", frames * 1000 / (start - lastDebug), drawTime / frames)
			frames, drawTime, lastDebug = 0, 0, start
		end
	end
	for _, hook in ipairs(frameHooks) do
		local ok, err = pcall(hook, start)
		if not ok then
			ConPrintf("PoE Tree Overlay: %s", tostring(err))
			debug("error: %s", tostring(err))
		end
	end
end

-- input seen (for "speed"), and the tree hotkeys
local lastInput = GetTime()
local function wrapInput(name, handler)
	local real = launch[name]
	launch[name] = function(self, key, ...)
		lastInput = GetTime()
		if handler and handler(key) then
			return
		end
		return real(self, key, ...)
	end
end

local function switchTree(step)
	local b = buildMode()
	if not b or main.popups[1] or launch.promptMsg then
		return false
	end
	local treeTab = b.treeTab
	local index = treeTab.activeSpec + step
	if treeTab.specList[index] then
		b.modFlag = true
		treeTab:SetActiveSpec(index)
	end
	return true
end

wrapInput("OnKeyDown", on("keys") and function(key)
	if (key == "UP" or key == "DOWN") and IsKeyDown("CTRL") then
		return switchTree(key == "UP" and -1 or 1)
	end
end)
wrapInput("OnKeyUp")
wrapInput("OnChar")

-- speed -------------------------------------------------------------------------------
if on("speed") then
	local ffi = require("ffi")
	pcall(ffi.cdef, [[
		void Sleep(uint32_t ms);
		void *GetForegroundWindow(void);
		uint32_t GetWindowThreadProcessId(void *hwnd, uint32_t *pid);
		uint32_t GetCurrentProcessId(void);
	]])
	local okWinmm, winmm = pcall(ffi.load, "winmm")
	if okWinmm then
		pcall(ffi.cdef, "uint32_t timeBeginPeriod(uint32_t ms);")
		winmm.timeBeginPeriod(1)
	end
	local C = ffi.C
	local myPid = C.GetCurrentProcessId()
	local pidBuf = ffi.new("uint32_t[1]")
	local lastX, lastY = GetCursorPos()
	local lastFocusCheck, focused = 0, true

	local function busy()
		for co in pairs(coroutine._list and coroutine._list() or { }) do
			if coroutine.status(co) == "suspended" then
				return true
			end
		end
		return false
	end

	table.insert(frameHooks, function(start)
		local now = GetTime()
		if now - lastFocusCheck > 250 then
			lastFocusCheck = now
			pidBuf[0] = 0
			C.GetWindowThreadProcessId(C.GetForegroundWindow(), pidBuf)
			focused = pidBuf[0] == myPid
		end
		local x, y = GetCursorPos()
		if x ~= lastX or y ~= lastY then
			lastX, lastY = x, y
			if focused then
				lastInput = now
			end
		end
		if busy() then
			return
		end
		-- frame time: unlimited while you use it, 20 fps when idle, 5 in the background
		local frame
		if not focused then
			frame = 200
		elseif now - lastInput > 1500 then
			frame = 50
		else
			return
		end
		local wait = frame - (now - start)
		if wait > 0 then
			C.Sleep(wait)
		end
	end)
end

-- link --------------------------------------------------------------------------------
if on("link") then
	local lastKey, changedAt, written = nil, 0, nil

	local function writeFile(name, text)
		local tmp = DIR .. name .. ".tmp"
		local f = io.open(tmp, "wb")
		if not f then
			return false
		end
		f:write(text)
		f:close()
		os.remove(DIR .. name)
		return os.rename(tmp, DIR .. name)
	end

	table.insert(frameHooks, function()
		local b = buildMode()
		local key
		if b then
			key = table.concat({ b.dbFileName or "", b.buildName or "", b.treeTab.activeSpec, b.outputRevision or 0 }, "\n")
		else
			key = "none"
		end
		local now = GetTime()
		if key ~= lastKey then
			lastKey, changedAt = key, now
		end
		-- write once things settle (a quarter second after the last change)
		if key == written or now - changedAt < 250 then
			return
		end
		written = key
		if not b then
			writeFile("pob_live.txt", "none\n")
			return
		end
		local xml = b:SaveDB(b.dbFileName or "live")
		if xml and writeFile("pob_live.xml", xml) then
			writeFile("pob_live.txt", key .. "\n" .. (b.unsaved and "unsaved" or "saved") .. "\n")
		end
	end)
end

-- marks -------------------------------------------------------------------------------
if on("marks") then
	local marks, lastRead, lastText = nil, -10000, nil

	local function norm(path)
		return path and path:gsub("\\", "/"):lower() or ""
	end

	local function readMarks()
		local f = io.open(DIR .. "pob_marks.txt", "r")
		if not f then
			marks = nil
			return
		end
		local text = f:read("*a")
		f:close()
		if text == lastText then
			return
		end
		lastText = text
		local m = { alloc = { }, route = { } }
		for line in text:gmatch("[^\n]+") do
			local key, rest = line:match("^(%w+)\t(.*)$")
			if key == "build" then
				m.build = norm(rest)
			elseif key == "tree" then
				m.tree = tonumber(rest)
			elseif key == "alloc" then
				for id in rest:gmatch("%d+") do
					m.alloc[tonumber(id)] = true
				end
			elseif key == "route" then
				for id in rest:gmatch("%d+") do
					table.insert(m.route, tonumber(id))
				end
			end
		end
		marks = m
	end

	table.insert(frameHooks, function()
		local now = GetTime()
		if now - lastRead > 1000 then
			lastRead = now
			readMarks()
		end
	end)

	local function drawMarks(view, build, viewPort)
		local b = buildMode()
		if not marks or not b or build ~= b or norm(b.dbFileName) ~= marks.build then
			return
		end
		local spec = build.spec
		local tree = spec.tree
		local scale = math.min(viewPort.width, viewPort.height) / tree.size * view.zoom
		local offsetX = view.zoomX + viewPort.x + viewPort.width / 2
		local offsetY = view.zoomY + viewPort.y + viewPort.height / 2
		local x0, y0 = viewPort.x, viewPort.y
		local x1, y1 = x0 + viewPort.width, y0 + viewPort.height
		SetDrawLayer(nil, 35)
		for id in pairs(marks.alloc) do
			local node = spec.nodes[id]
			if node and node.x and not node.ascendancyName then
				local x, y = node.x * scale + offsetX, node.y * scale + offsetY
				local r = (node.size or 50) * scale * 1.5
				if x + r > x0 and x - r < x1 and y + r > y0 and y - r < y1 then
					if spec.allocNodes[id] then
						SetDrawColor(0.2, 0.85, 0.35)
					else
						SetDrawColor(1, 0.25, 0.25)
					end
					DrawImage(view.highlightRing, x - r, y - r, r * 2, r * 2)
				end
			end
		end
		if marks.tree == b.treeTab.activeSpec then
			local h = math.max(12, math.min(22, math.floor(60 * scale + 8)))
			for i, id in ipairs(marks.route) do
				local node = spec.nodes[id]
				if node and node.x then
					local x, y = node.x * scale + offsetX, node.y * scale + offsetY
					if x > x0 and x < x1 and y > y0 and y < y1 then
						local text = tostring(i)
						local w = math.max(h, DrawStringWidth(h - 4, "VAR BOLD", text) + 8)
						SetDrawColor(0.039, 0.518, 1.0)
						DrawImage(nil, x - w / 2, y - h / 2, w, h)
						SetDrawColor(1, 1, 1)
						DrawString(x, y - (h - 4) / 2 - 1, "CENTER_X", h - 4, "VAR BOLD", text)
					end
				end
			end
		end
		SetDrawColor(1, 1, 1)
	end

	local wrapped = false
	table.insert(frameHooks, function()
		local cls = not wrapped and common and common.classes and common.classes.PassiveTreeView
		if cls then
			wrapped = true
			local draw = cls.Draw
			cls.Draw = function(self, build, viewPort, inputEvents)
				draw(self, build, viewPort, inputEvents)
				local ok, err = pcall(drawMarks, self, build, viewPort)
				if not ok then
					ConPrintf("PoE Tree Overlay marks: %s", tostring(err))
				end
			end
		end
	end)
end
