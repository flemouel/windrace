
// --------------------------------------------
// Query string
// --------------------------------------------

var QUERYSTRING	= new Array();

//var lArr = location.search.substr(1).replace(/\%26/g,"&").split("&");
var lArr = location.search.substr(1).split("&");

for (var lIdx=0; lIdx<lArr.length; lIdx++)
{
	var lArrValue = lArr[lIdx].split("=");
	QUERYSTRING[lArrValue[0]] = lArrValue[1]; 
}
// --------------------------------------------
// String trim
// --------------------------------------------
// Removes leading whitespaces
function LTrim( value ) {
	
	var re = /\s*((\S+\s*)*)/;
	return value.replace(re, "$1");
	
}

// Removes ending whitespaces
function RTrim( value ) {
	
	var re = /((\s*\S+)*)\s*/;
	return value.replace(re, "$1");
	
}

// Removes leading and ending whitespaces
function trim( value ) {
	
	return LTrim(RTrim(value));
	
}

function getGeoLocation(iFnCallBack, iDefaultLocation)
{
    if(navigator.geolocation) 
    {
		navigator.geolocation.getCurrentPosition(function(position) 
		{
			if (typeof(iFnCallBack)=='function')
            {
                iFnCallBack(new google.maps.LatLng(position.coords.latitude,position.coords.longitude));
            }
        },
		function(error) 
		{
            if (typeof(iFnCallBack)=='function')
            {
                iFnCallBack(iDefaultLocation);
            }
        }
		);
    } 
    else 
	{
		if (typeof(iFnCallBack)=='function')
		{
			iFnCallBack(iDefaultLocation);
		}
	}
    
}

function getColor(lIdx)
{
	var lColorIdx = lIdx%arrColors.length;
    return arrColors[lColorIdx];
}

 function getNiceTime(iNmTime)
{
    var sec = iNmTime;
	
    var hours =  parseInt(sec/3600);
    sec -= hours*3600;
    var mins =  parseInt(sec/60);
    sec -= parseInt(mins*60);
    var lStrReturn = addZeros(hours)+":"+addZeros(mins)+":"+addZeros(parseInt(sec));
    return lStrReturn;
}
function addZeros(iStr)
{
    if(iStr<=9&&iStr>-1)
    {
        return "0"+ iStr;
    }
    return iStr;
}
 function getObjectType()
{
	if (QUERYSTRING['event'])
	{
		return 'event';
	}
	else if (QUERYSTRING['race'])
	{
		return 'race';
	}
	else if (QUERYSTRING['track'])
	{
		return 'track';
	}
	else
	{
		return 'track';
	}
}

// time

function timestampToString(iTimestamp)
{
	var date = new Date(iTimestamp*1000);
	var dateString = date.getFullYear()+".";
	if (date.getMonth()<=8) dateString += "0"+(date.getMonth()+1)+".";
	else dateString += (date.getMonth()+1)+".";
	if (date.getDate()<=9) dateString += "0"+(date.getDate())+" ";
	else dateString += (date.getDate())+" ";
	if (date.getHours()<=9) dateString += "0"+(date.getHours())+":";
	else dateString += (date.getHours())+":";
	if (date.getMinutes()<=9) dateString += "0"+(date.getMinutes())+"";
	else dateString += (date.getMinutes())+"";
	
	return dateString;
}

function timestampOffsetToString(iTimestamp, iOffset)
{
	var localDate = new Date();
	var localOffset = (localDate.getTimezoneOffset() * 60);
	var offsetDate = new Date(iTimestamp*1000);
	var timestamp = offsetDate.getTime()/1000 + iOffset + localOffset;

	var date = new Date(timestamp*1000);
	var dateString = date.getFullYear()+".";
	if (date.getMonth()<=8) dateString += "0"+(date.getMonth()+1)+".";
	else dateString += (date.getMonth()+1)+".";
	if (date.getDate()<=9) dateString += "0"+(date.getDate())+" ";
	else dateString += (date.getDate())+" ";
	if (date.getHours()<=9) dateString += "0"+(date.getHours())+":";
	else dateString += (date.getHours())+":";
	if (date.getMinutes()<=9) dateString += "0"+(date.getMinutes())+"";
	else dateString += (date.getMinutes())+"";
	
	return dateString;
}

function stringToTimestamp(iString)
{
	var year = 1970;
	var month = 0;
	var day = 0;
	var hours = 0;
	var minutes = 0;

	
	var datetimesplit = iString.split(" ");
	if (datetimesplit.length >=2)
	{
		var datesplit = datetimesplit[0].split(".");
		if (datesplit.length >=1) if (!isNaN(datesplit[0])) year = parseInt(datesplit[0]);
		if (datesplit.length >=2) if (!isNaN(datesplit[1])) month = parseInt(datesplit[1])-1;
		if (datesplit.length >=3) if (!isNaN(datesplit[2])) day = parseInt(datesplit[2]);
		
		var timesplit = datetimesplit[1].split(":");
		
		if (timesplit.length >=1) if (!isNaN(timesplit[0])) hours = parseInt(timesplit[0]);
		if (timesplit.length >=1) if (!isNaN(timesplit[1])) minutes = parseInt(timesplit[1]);
	}
	
	var date = new Date(year, month, day, hours, minutes, 0, 0)
	
	return Math.round(date.getTime()/1000);
}
function stringToTimestampUTC(iString,iOffset)
{
	var localDate = new Date();
	var localOffset = (localDate.getTimezoneOffset() * 60);
	var timestamp = stringToTimestamp(iString) - iOffset - localOffset;
	return timestamp;
}
// geo

function getCoordinateDegrees(iCoordinate)
{
	var deg = Math.floor(iCoordinate);
	if(iCoordinate<0) deg = Math.ceil(iCoordinate);
	return Math.abs(deg);
}
function getCoordinateMinutes(iCoordinate)
{
	var deg = Math.floor(iCoordinate);
	if(iCoordinate<0) deg = Math.ceil(iCoordinate);
	
	var min = (iCoordinate-deg)*60;
	min = Math.round(min*1000000)/1000000;
	
	return Math.abs(min);
}
function getCoordinateSign(iCoordinate,iPositive,iNegative)
{
	if (iCoordinate>=0) return iPositive;
	else return iNegative;
}

function getShift(fromDirection,toDirection)
{
	var s = toDirection - fromDirection;
	if (s<0) s = 360 + s;
	if (s>180) s = s - 360;
		
	return s;
}
	