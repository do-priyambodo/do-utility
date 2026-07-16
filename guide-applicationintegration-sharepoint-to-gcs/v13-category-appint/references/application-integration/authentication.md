{# DO NOT MODIFY THE FOLLOWING LINE #}
{% extends "_shared/templates/_authentication.html" %}


{% block pagevariables %}

{% include "application-integration/_local_variables.html" %}
<meta name="book_path" value="{{book_path}}" />
<meta name="project_path" value="{{project_path}}" />
<meta name="description" content="Learn how to authenticate with {{product_name}}">

{% setvar launch_stage %}{% endsetvar %}
{% setvar launch_type %}product{% endsetvar %}

{% comment %}
Valid values are `service_account`, `end_user`, and `api_keys`.
{% endcomment %}
{% setvar authentication_methods %}service_account,end_user{% endsetvar %}

{% comment %}
If your "APIs and reference" landing page is in a
nonstandard location, update the `reference_link` variable to point to the
landing page. Otherwise, keep the variable as-is.
{% endcomment %}
{% setvar reference_link %}{{root_path}}docs/apis{% endsetvar %}

{% comment %}
If your "APIs and reference" landing page uses a nonstandard
title, update the `reference_link_title` variable to use the correct title.
Otherwise, keep the variable as-is.
{% endcomment %}
{% setvar reference_link_title %}APIs and reference{% endsetvar %}

{% comment %}
If customers can authenticate with end-user credentials,
specify a list of use cases for this authentication method. For example,
"Building dashboard apps with BigQuery."

Wrap each example in an <li> tag:

  <li>An example</li>
  <li>Another example</li>

{% endcomment %}
{% setvar end_user_examples_list %}{% endsetvar %}

{% comment %}
If customers can authenticate with API keys, specify a list
of use cases for this authentication method. API keys are discouraged in almost
all use cases. If you don't know your product's use cases for API keys, contact
your PM, DPE, or cloud-auth-docs@.

Wrap each example in an <li> tag:

  <li>An example</li>
  <li>Another example</li>

{% endcomment %}
{% setvar api_key_examples_list %}{% endsetvar %}

{% comment %}
if your product has specialized authentication topics,
specify a list of links to those topics.

Wrap each link in an <li> tag:

  <li><a href="/application-integration/docs/authentication-1">Specialized topic 1</a></li>
  <li><a href="/application-integration/docs/authentication-2">Specialized topic 2</a></li>

{% endcomment %}
{% setvar auth_more_information_list %}{% endsetvar %}

{% endblock %}
