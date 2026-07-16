{# DO NOT MODIFY THE FOLLOWING LINE #}
{% extends "_shared/templates/_doc_specific_landing_page.html" %}
{% block pagevariables %}
{% include "application-integration/docs/_shared/_integration_connector_localvars.html" %}
{% include "application-integration/_local_variables.html" %}

{% setvar landing_page_title %}All tutorials {% endsetvar %}
<meta name="book_path" value="{{book_path}}" />
<meta name="project_path" value="{{project_path}}" />
<meta name="description" content="Understand how {{product_name_short}} works" />

{% endblock %}

{% block doclinks %}

<p>
This page provides links to some {{integration}} tutorials that you use to get started.
</p>

<div class="card" id="all-concepts">

  <ul class="card-showcase">

    {% setvar lp_title %}Route and fetch information for an ingress API request{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/api-fulfilment{% endsetvar %}
    {% setvar lp_desc %}
    Receive API requests for retrieving customer information and based on the API request location, retrieve the customer details from either a MySQL database or an Oracle database.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Automate Salesforce case routing assignments{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/automate-salesforce-case-routing{% endsetvar %}
    {% setvar lp_desc %}
    Automate the business process flow of routing and assigning a Salesforce customer case.
    {% endsetvar %}
    
    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Automate Salesforce opportunity to BigQuery order{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/automate-salesforce-opportunity-to-bigquery-order{% endsetvar %}
    {% setvar lp_desc %}
    Automate an order management flow between a customer relationship management (CRM) application and an enterprise resource planning (ERP) application.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Invoke an integration for a Salesforce Change Data Capture (CDC) event{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/invoke-integration-salesforce-cdc-event{% endsetvar %}
    {% setvar lp_desc %}
    Use the Salesforce trigger to invoke an integration in Application Integration for a Salesforce Change Data Capture (CDC) event.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Perform CRUD operations on a MySQL database{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/perform-crud-operation-mysql-database{% endsetvar %}
    {% setvar lp_desc %}
    Connect to a MySQL database instance from a sample integration and perform the list, get, create, update, and delete operations on a MySQL database table.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

    {% setvar lp_title %}Insert data into BigQuery using a For Each Parallel task to process a series of records{% endsetvar %}
    {% setvar lp_link %}{{root_path}}docs/insert-data-bigquery-for-each-parallel-task{% endsetvar %}
    {% setvar lp_desc %}
    Create an integration and a sub-integration to process a series of records and inserts it as a row in a table in a BigQuery dataset.
    {% endsetvar %}

    {% include "_shared/templates/_landing_page_card.html" %}

  </ul>
</div>

{% endblock %}
