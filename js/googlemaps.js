$(document).ready(function()
{ 
	var script = document.createElement("script");   
	script.type = "text/javascript";   
	
	script.src = "https://maps.googleapis.com/maps/api/js?key=AIzaSyBUlP02TvPbUKhENV7qOFJxjMhIu-XJaJo&callback=googleMapsLoaded&libraries=visualization,geometry";   
	document.body.appendChild(script); 
}); 
 
function googleMapsLoaded()
{
	$.getScript("/js/usgsoverlay.js", function() 
	{
		if (typeof(readyWithGoogle)=="function")
		{
			window.setTimeout("readyWithGoogle()",500);
		}
		
		$("#overlay_chart").change(function(){onChartChange($("#overlay_chart").val());});
		
	});
}

var overlay_chart_array = new Array();
	
function onChartChange(chartid)
{
	$.getJSON("/webservice/chart.php",{mode:"get", id:chartid },function(data)
	{
		if(data)
		{
			
			for(var overlay_index in overlay_chart_array)
			{
				overlay_chart_array[overlay_index].setMap(null);
			}
				
			var lat_shift_per_row = getShift(data["lat1"],data["lat2"])/data["rows"];
			var lng_shift_per_col = getShift(data["lng1"],data["lng2"])/data["cols"];
				
			for (var c=0; c<data["cols"]; c++)
			{
				for (var r=0; r<data["rows"]; r++)
				{
					
						
					var lat1 = parseFloat(data["lat1"])+r*lat_shift_per_row + parseFloat(data["lat_offset"])*Math.sin(r*Math.PI/(data["rows"]));
					var lng1 = parseFloat(data["lng1"])+c*lng_shift_per_col;
					var lat2 = parseFloat(data["lat1"])+(r+1)*lat_shift_per_row + parseFloat(data["lat_offset"])*Math.sin((r+1)*Math.PI/(data["rows"]));
					var lng2 = parseFloat(data["lng1"])+(c+1)*lng_shift_per_col;
					
					//alert(lat1+"\n"+lng1+"\n"+lat2+"\n"+lng2+"\n"+"/charts/"+data["id"]+"_"+c+"_"+r+".jpg")
					var cellBound = new google.maps.LatLngBounds();
					cellBound.extend(new google.maps.LatLng(lat1,lng1));
					cellBound.extend(new google.maps.LatLng(lat2,lng2));
					
					var groundOverlay = new google.maps.GroundOverlay("/charts/"+data["id"]+"_"+c+"_"+r+".jpg", cellBound, {opacity:0.2,clickable:false});
					groundOverlay.setMap(map);
					
					overlay_chart_array[overlay_chart_array.length] = groundOverlay;
						
				}
			}
		}
	});	
	
}

	