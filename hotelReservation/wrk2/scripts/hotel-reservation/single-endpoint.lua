local socket = require("socket")
math.randomseed(socket.gettime() * 1000)
math.random(); math.random(); math.random()

local target = os.getenv("HOTEL_RESERVATION_TARGET") or "hotels"

local function random_date_range()
  local in_date = math.random(9, 23)
  local out_date = math.random(in_date + 1, 24)

  local function fmt(day)
    if day <= 9 then
      return "2015-04-0" .. tostring(day)
    end
    return "2015-04-" .. tostring(day)
  end

  return fmt(in_date), fmt(out_date)
end

local function random_location()
  local lat = 38.0235 + (math.random(0, 481) - 240.5) / 1000.0
  local lon = -122.095 + (math.random(0, 325) - 157.0) / 1000.0
  return lat, lon
end

local function get_user()
  local id = math.random(0, 500)
  local username = "Cornell_" .. tostring(id)
  local password = ""
  for _ = 0, 9, 1 do
    password = password .. tostring(id)
  end
  return username, password
end

local function search_hotel()
  local in_date, out_date = random_date_range()
  local lat, lon = random_location()
  local path = "/hotels?inDate=" .. in_date ..
    "&outDate=" .. out_date ..
    "&lat=" .. tostring(lat) ..
    "&lon=" .. tostring(lon)
  return wrk.format("GET", path, {}, nil)
end

local function recommend()
  local coin = math.random()
  local require = "price"
  if coin < 0.33 then
    require = "dis"
  elseif coin < 0.66 then
    require = "rate"
  end

  local lat, lon = random_location()
  local path = "/recommendations?require=" .. require ..
    "&lat=" .. tostring(lat) ..
    "&lon=" .. tostring(lon)
  return wrk.format("GET", path, {}, nil)
end

local function user_login()
  local username, password = get_user()
  local path = "/user?username=" .. username .. "&password=" .. password
  return wrk.format("POST", path, {}, nil)
end

local function reserve()
  local in_date, out_date = random_date_range()
  local hotel_id = tostring(math.random(1, 80))
  local username, password = get_user()
  local customer_name = username
  local path = "/reservation?inDate=" .. in_date ..
    "&outDate=" .. out_date ..
    "&hotelId=" .. hotel_id ..
    "&customerName=" .. customer_name ..
    "&username=" .. username ..
    "&password=" .. password ..
    "&number=1"
  return wrk.format("POST", path, {}, nil)
end

request = function()
  if target == "hotels" then
    return search_hotel()
  elseif target == "recommendations" then
    return recommend()
  elseif target == "user" then
    return user_login()
  elseif target == "reservation" then
    return reserve()
  end

  error("Unsupported HOTEL_RESERVATION_TARGET: " .. target)
end
