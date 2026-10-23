(function () {
  "use strict";
  var LIVE = JSON.parse(document.getElementById("pool-data").textContent);
  var DATA = LIVE;          // what's on screen: the live page, or the owner's preview
  var TITLE = "ACQL · Arm Chair Quarterback League";
  var FONTS = [
    "https://fonts.googleapis.com/css2?family=Big+Shoulders:opsz,wght@10..72,700..900&display=swap",
    "https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@700;800;900&display=swap",
    "https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700&family=Barlow+Condensed:wght@600;700;800&display=swap",
    "https://fonts.googleapis.com/css2?family=Rajdhani:wght@500;600;700&display=swap"
  ];
  var ME_KEY = "acql-pool-me", THEME_KEY = "acql-theme", TEXT_KEY = "acql-text", VS_KEY = "acql-pool-vs";
  var app = document.getElementById("app");
  var state = { view: "home", week: DATA.through_week, me: stored(ME_KEY), coach: "", a: "", b: "",
    sheet: false, every: false, chartMe: "", picksOrder: "" };
  var updateBar = null;     // the owner's update controls, kept across redraws

