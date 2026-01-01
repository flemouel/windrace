  var overlay;
 
  USGSOverlay.prototype = new google.maps.OverlayView();
 
  function USGSOverlay(point, image, map, angle, title, boatClick, hideFlag) 
  {
 
    // Now initialize all properties.
    this.point_ = point;
    this.image_ = image;
    this.map_ = map;
    this.angle_ = angle||0;
	this.speed_ = 0;
	this.title_ = title||0;
    this.timeout = null;
	this.blinkTimeout = null;
	this.blinked = false;
    this.moveTime = 1000;
	this.blShowName = true;
	this.blShowSpeed = true;
	this.blShowDirection = true;
	this.boatClick = boatClick||function(){};
    // We define a property to hold the image's div. We'll 
    // actually create this div upon receipt of the onAdd() 
    // method so we'll leave it null for now.
    this.divName_ = null;
	this.divSpeed_ = null;    
	this.divDirection_ = null;
	this.img_ = null;
	this.div_ = null;
	
	//if (typeof(hideFlag)!=undefined) this.hideFlag = hideFlag;
    //else 
	this.hideFlag = false;
	
    // Explicitly call setMap on this overlay
    this.setMap(map);
  }
 
  USGSOverlay.prototype.onAdd = function() {
 
    // Note: an overlay's receipt of onAdd() indicates that
    // the map's panes are now available for attaching
    // the overlay to the map via the DOM.
 
    // Create the DIV and set some basic attributes.
	
    var div = document.createElement('DIV');
	div.className = "boatInfo";
    div.style.borderStyle = "none";
    div.style.borderWidth = "0px";
	div.style.overflow = "hidden";
	div.style.textOverflow= "ellipsis";
	div.style.whiteSpace = "nowrap";
    div.style.position = "absolute";
	div.style.width = "200px";
	div.style.zIndex = "200";
    div.style.textAlign = "left";
	div.style.display = "none";//this.hideFlag?"none":"";
	//div.style.visibility = "hidden";this.hideFlag?"hidden":"visible";
	
	
	var divName = document.createElement('DIV');
	divName.style.borderStyle = "none";
    divName.style.borderWidth = "0px";
	divName.style.overflow = "hidden";
	divName.style.textOverflow= "ellipsis";
	divName.style.whiteSpace = "nowrap";
	divName.style.width = "200px";
	divName.style.zIndex = "200";
    divName.style.textAlign = "left";
	divName.style.display = this.blShowName?"":"none";
	//divName.style.visibility = this.blShowName?"visible":"hidden";
	divName.innerHTML = this.title_; // todo change
	div.appendChild(divName);
	
	var divSpeed = document.createElement('DIV');
	divSpeed.style.borderStyle = "none";
    divSpeed.style.borderWidth = "0px";
	divSpeed.style.overflow = "hidden";
	divSpeed.style.textOverflow= "ellipsis";
	divSpeed.style.whiteSpace = "nowrap";
	divSpeed.style.width = "200px";
	divSpeed.style.zIndex = "200";
    divSpeed.style.textAlign = "left";
	divSpeed.style.display = this.blShowSpeed?"":"none";
	//divSpeed.style.visibility = this.blShowSpeed?"visible":"hidden";
	divSpeed.innerHTML = (this.speed_*1.9438612860586).toFixed(1)+"kn";
	div.appendChild(divSpeed);
	
	var divDirection = document.createElement('DIV');
	divDirection.style.borderStyle = "none";
    divDirection.style.borderWidth = "0px";
	divDirection.style.overflow = "hidden";
	divDirection.style.textOverflow= "ellipsis";
	divDirection.style.whiteSpace = "nowrap";
	divDirection.style.width = "100px";
	divDirection.style.zIndex = "200";
    divDirection.style.textAlign = "left";
	divDirection.style.display = this.blShowDirection?"":"none";
	//divDirection.style.visibility = this.blShowDirection?"visible":"hidden";
	divDirection.innerHTML = this.angle_+"&ordm; ";
	div.appendChild(divDirection);
	
	
	
    var img = document.createElement("div");
    img.style.backgroundImage = "url("+this.image_+")";
    img.style.position = "absolute";
    img.style.width = "100px";
    img.style.height = "100px";
    img.style.zIndex = "199";
	img.style.borderStyle = "none";
    img.style.borderWidth = "0px";
    img.style.display = "none";//this.hideFlag?"none":"";
	//img.style.visibility = "hidden";//this.hideFlag?"hidden":"visible";
	img.style.cursor = "pointer";
	
   
 
    // Set the overlay's div_ property to this DIV
    this.divDirection_ = divDirection;
	this.divSpeed_ = divSpeed;
	this.divName_ = divName;
	this.div_ = div;
    this.img_ = img;
    
    // We add an overlay to a map via one of the map's panes.
    // We'll add this overlay to the overlayImage pane.
    var panes = this.getPanes();
    
    panes.overlayImage.appendChild(img);
	panes.overlayImage.appendChild(div);
	$(img).click(this.boatClick);	
	$(div).click(this.boatClick);	
//	this.test = document.createElement("div");
//    this.test.style.backgroundImage = "url(css/marker.png)";
//	this.test.style.position = "absolute";
//    this.test.style.width = "10px";
//    this.test.style.height = "10px";
//    this.test.style.zIndex = "199";
//	
//	panes.overlayImage.appendChild(this.test);
//	
	//$(divName).ellipsis();
	var me = this;
	/*
	function BlinkBoat()
	{
		if (me.img_ && !me.hideFlag)
		{
			if (me.speed_!=null)
			{
				//$(me.div_).html(me.speed_.toFixed(1));
				if ( me.speed_ == 0.0)
				{
					if (me.blinked)
					{
						me.blinked = false;
						if (me.img_.style.visibility != "visible")
						{
							me.img_.style.visibility = "visible";
						}
					}
					else
					{
						me.blinked = true;
						if (me.img_.style.visibility != "hidden")
						{
							me.img_.style.visibility = "hidden";
						}
					}
				}
				else 
				{
					if (me.img_.style.visibility != "visible")
					{
						me.img_.style.visibility = "visible";
					}
				}
			}
		}
		window.setTimeout(BlinkBoat, 330);
	}
	window.setTimeout(BlinkBoat, 10);
	*/
	if (me.hideFlag==false) me.show();
	else  me.hide();
  }
 
  USGSOverlay.prototype.draw = function() 
  {
	if (this.hideFlag)
	{
		return;
	}
	var me = this;
	window.clearTimeout(this.timeout);
	this.timeout = window.setTimeout(function()
	{
		//var time1 = (new Date()).getTime();
		var overlayProjection = me.getProjection();
		if (typeof(overlayProjection)=="undefined") return;
		var point = overlayProjection.fromLatLngToDivPixel(me.point_);
		var lObjCor = getCorrection(me.angle_);
		me.divDirection_.innerHTML = lObjCor.angle.toFixed(0)+"&ordm;";
		var lStrSpeed = (me.speed_*1.9438612860586).toFixed(1)+"kn";
		
		me.divSpeed_.innerHTML = lStrSpeed;
		//me.img_ = $(me.img_).rotate(me.angle_,true);
		var x = point.x;
		var y = point.y;
		var width = 100;
		//if ( $.browser.msie && parseInt($.browser.version)<9)
		//removed if ( $.browser.msie )
		//{
		//	width = Math.abs(lObjCor.sin * width)+Math.abs(lObjCor.cos * width);
		//}
		x -= width/2;
		y -= width/2;
		//$(me.div_).html(me.angle_.toFixed(1));
		//$(me.img_).css({left:point.x-25,top:point.y-25
		$(me.img_).css({left:x,top:y
			,
			'-moz-transform':"rotate("+me.angle_+"deg)",/* FF3.5+ */
			'-o-transform': "rotate("+me.angle_+"deg)",  /* Opera 10.5 */
			'-webkit-transform': "rotate("+me.angle_+"deg)",  /* Saf3.1+, Chrome */
			'-ms-transform': "rotate("+me.angle_+"deg)",  /* IE9 */
			'transform': "rotate("+me.angle_+"deg)",
             filter: "progid:DXImageTransform.Microsoft.Matrix( M11="+lObjCor.cos+", M12="+(-1*lObjCor.sin)+",M21="+lObjCor.sin+", M22="+lObjCor.cos+", sizingMethod='auto expand')"
              });
		
		var lIncX = 0;
		if (me.angle_>180 || me.angle_<0)
		{
			lIncX = Math.abs(lObjCor.sin * 25);
		}
		
		$(me.div_).css({left:point.x+5+lIncX,top:point.y-8});
		//$(me.test).css({left:point.x-5,top:point.y-5});
	},10);
  }
  
  
  function getLatLonFromGooglePoint(point)
  {
      var lat= Geo.parseDMS(point.lat());
      var lon = Geo.parseDMS(point.lng());
      return new LatLon(lat, lon);
  }
  function getCorrection(angle)
  {
      angle = angle%360;
      if (angle >= 0) {
		var rotation = Math.PI * angle / 180;
	} else {
		var rotation = Math.PI * (360+angle) / 180;
	}
	var costheta = Math.cos(rotation);
	var sintheta = Math.sin(rotation);
    return {cos:costheta,sin:sintheta,angle:angle};
  }
  
  USGSOverlay.prototype.rotate = function(iNmAngle) 
  {
    //$(this.img_).rotate(iNmAngle);
  }
  
  USGSOverlay.prototype.move = function(point,iNmAngle,iNmSpeed)
  {
    this.angle_ = typeof(iNmAngle)!="undefined"?iNmAngle:this.angle_;
	this.speed_ = typeof(iNmSpeed)!="undefined"?iNmSpeed:this.speed_;
    this.angle_ = isNaN(this.angle_)?0:this.angle_;
	this.speed_ = isNaN(this.speed_)?0:this.speed_;
    this.point_  = point;
	// console.log(point.lat()+" "+point.lng()) // Commenté pour réduire le spam
    this.draw();
  }
 
  
 
  USGSOverlay.prototype.onRemove = function() 
  {
    console.log("remove", "in over");
	
	this.div_.parentNode.removeChild(this.div_);
    this.div_ = null;
	
	this.img_.parentNode.removeChild(this.img_);
	this.setMap(null);
	
  }
  
  // Note that the visibility property must be a string enclosed in quotes
USGSOverlay.prototype.hide = function(iBlOnlyBoat) 
{
  this.hideFlag = true;
  if (this.img_) 
  {
    this.img_.style.visibility = "hidden";
    this.img_.style.display = "none";
	if(!iBlOnlyBoat)
	{
		this.div_.style.display = "none";
	}
  }
}

USGSOverlay.prototype.show = function() 
{
	var overlayProjection = this.getProjection();
	if (typeof(overlayProjection)=="undefined") return;
	this.hideFlag = false;
	if (this.img_ && this.div_) 
	{
		this.img_.style.visibility = "visible";
		this.img_.style.display = "";
		this.div_.style.display = "";

		if (this.divName_)
		{
			this.divName_.style.display = this.blShowName?"":"none";
		}
		if (this.divSpeed_)
		{
			this.divSpeed_.style.display = this.blShowSpeed?"":"none";
		}
		if (this.divDirection_)
		{
			this.divDirection_.style.display = this.blShowDirection?"":"none";
		}
	}
}



USGSOverlay.prototype.showName = function(iBlShow) 
{
	this.blShowName = iBlShow;
	if (this.divName_) 
	{
		if ((this.hideFlag==false)&&(this.blShowName==true)) this.divName_.style.display = "";
		else this.divName_.style.display = "none";
	}
}
USGSOverlay.prototype.showSpeed = function(iBlShow) 
{
	this.blShowSpeed = iBlShow;
	if (this.divSpeed_ ) 
	{
		if ((this.hideFlag==false)&&(this.blShowSpeed==true)) this.divSpeed_.style.display = "";
		else this.divSpeed_.style.display = "none";
	}
}

USGSOverlay.prototype.showDirection = function(iBlShow) 
{
	this.blShowDirection = iBlShow;
	if (this.divDirection_) 
	{
		if ((this.hideFlag==false)&&(this.blShowDirection==true)) this.divDirection_.style.display = "";
		else this.divDirection_.style.display = "none";
		
	}
}
USGSOverlay.prototype.toggle = function() {
  if (this.img_) {
    //if (this.img_.style.visibility == "hidden") {
    if (this.img_.style.display == "none") {
      this.show();
    } else {
      this.hide();
    }
  }
}

USGSOverlay.prototype.toggleDOM = function() {
  if (this.getMap()) {
    this.setMap(null);
  } else {
    this.setMap(this.map_);
  }
}