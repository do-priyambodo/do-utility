{# DO NOT MODIFY THE FOLLOWING LINE #}
{% extends "_shared/templates/_release_notes.html" %}

{% block pagevariables %}

{% include "application-integration/_local_variables.html" %}
<meta name="book_path" value="{{book_path}}" />
<meta name="project_path" value="{{project_path}}" />
<meta name="translation" value="disabled" />
<title>{{product_name}} release notes</title>


{% setvar xml_feed_url %}/feeds/application-integration-release-notes.xml{% endsetvar %}
{% endblock %}

{% block pagedescription %}
This page documents production updates to {{product_name}}.
Check this page for announcements about new or updated features, bug fixes,
known issues, and deprecated functionality.
{% endblock %}

{% block releases %}

{% getreleasenotes %}
paths:
- /application-integration/docs/release-notes/*
{% endgetreleasenotes %}

{% endblock %}













