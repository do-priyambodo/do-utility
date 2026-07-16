{# DO NOT MODIFY THE FOLLOWING LINE #}
{% extends "application-integration/_base.html" %}
{% include "application-integration/docs/_shared/_integration_connector_localvars.html" %}
{% include "application-integration/_local_variables.html" %}

{% block page_title %}All triggers and tasks{% endblock %}
<meta name="book_path" value="{{book_path}}" />
<meta name="project_path" value="{{project_path}}" />
<meta name="description" content="Understand Application Integration tasks and triggers" />
{% block body %}

<p>
This page introduces the various configurable triggers and tasks available in {{integration}}.
</p>
<h2>Triggers </h2>

{% include "application-integration/docs/_triggers-reference.html" %}

<h2 id="event_triggers">Connector Event triggers </h2>
{% include "application-integration/docs/_event-triggers-reference.html" %}

<h2>Tasks for Google Cloud services</h2>

{% include "application-integration/docs/_gcp-tasks-reference.html" %}

<h2>Integration tasks</h2>

{% include "application-integration/docs/_tasks-reference.html" %}

{% endblock %}